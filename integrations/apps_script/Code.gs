/**
 * Dobrolap booking bot ↔ Google Sheets bridge.
 *
 * Setup (owner / developer once):
 * 1. Open the spreadsheet «Размещение добролап».
 * 2. Extensions → Apps Script → paste this file → Save.
 * 3. Set SCRIPT_TOKEN below to a long random string (same as GAS_WEBAPP_TOKEN in .env).
 * 4. Deploy → New deployment → Type: Web app
 *    - Execute as: Me
 *    - Who has access: Anyone
 * 5. Copy the Web App URL into .env as GAS_WEBAPP_URL.
 * 6. Set GOOGLE_SHEETS_ENABLED=true
 *
 * Optional: change SHEET_NAME if the calendar tab has another title.
 */

var SCRIPT_TOKEN = "CHANGE_ME_TO_LONG_RANDOM_SECRET";
var SHEET_NAME = "Bookings";
var HEADERS = ["external_id", "unit_id", "date_from", "date_to", "status"];

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || "{}");
    if (body.token !== SCRIPT_TOKEN) {
      return json_({ ok: false, error: "unauthorized" });
    }
    var action = body.action || "";
    if (action === "list") {
      return json_({ ok: true, bookings: listBookings_() });
    }
    if (action === "upsert") {
      var b = body.booking || {};
      upsertBooking_(b);
      return json_({ ok: true, booking: b });
    }
    if (action === "ping") {
      return json_({ ok: true, sheet: SHEET_NAME });
    }
    return json_({ ok: false, error: "unknown_action" });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function doGet(e) {
  return json_({
    ok: true,
    service: "dobrolap-sheets-bridge",
    hint: "Use POST with action=list|upsert|ping",
  });
}

function listBookings_() {
  var sh = getOrCreateSheet_();
  var values = sh.getDataRange().getValues();
  if (values.length <= 1) {
    return [];
  }
  var out = [];
  for (var i = 1; i < values.length; i++) {
    var row = values[i];
    var externalId = String(row[0] || "").trim();
    var unitId = String(row[1] || "").trim();
    if (!externalId || !unitId) {
      continue;
    }
    out.push({
      external_id: externalId,
      unit_id: unitId,
      date_from: formatDate_(row[2]),
      date_to: formatDate_(row[3]),
      status: String(row[4] || "CONFIRMED").trim(),
    });
  }
  return out;
}

function upsertBooking_(b) {
  var sh = getOrCreateSheet_();
  var externalId = String(b.external_id || "").trim();
  if (!externalId) {
    throw new Error("external_id required");
  }
  var values = sh.getDataRange().getValues();
  var rowIndex = -1;
  for (var i = 1; i < values.length; i++) {
    if (String(values[i][0]).trim() === externalId) {
      rowIndex = i + 1; // 1-based
      break;
    }
  }
  var line = [
    externalId,
    String(b.unit_id || "").trim(),
    String(b.date_from || "").trim(),
    String(b.date_to || "").trim(),
    String(b.status || "").trim(),
  ];
  if (rowIndex === -1) {
    sh.appendRow(line);
  } else {
    sh.getRange(rowIndex, 1, 1, 5).setValues([line]);
  }
}

function getOrCreateSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    sh = ss.insertSheet(SHEET_NAME);
    sh.appendRow(HEADERS);
  } else if (sh.getLastRow() === 0) {
    sh.appendRow(HEADERS);
  }
  return sh;
}

function formatDate_(value) {
  if (Object.prototype.toString.call(value) === "[object Date]" && !isNaN(value)) {
    return Utilities.formatDate(value, Session.getScriptTimeZone(), "yyyy-MM-dd");
  }
  return String(value || "").trim();
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
