/**
 * Dobrolap bot ↔ real occupancy calendar (grid).
 *
 * Prod layout «Размещение добролап» / Лист1:
 *   A = category (Название), carried when blank
 *   B = room / number (Подкатегория)
 *   C.. = dates (Date cells; display may be «21.авг.»)
 *   Non-empty date cell = occupied (manual text or STATUS:bookingId)
 *
 * Setup:
 * 1. Open spreadsheet → Extensions → Apps Script → paste → Save
 * 2. Set SCRIPT_TOKEN and CALENDAR_SHEET below
 * 3. Deploy → Web app → Execute as Me, Who has access: Anyone
 * 4. Put URL + token into .env (GAS_WEBAPP_URL / GAS_WEBAPP_TOKEN)
 *
 * WARNING: this spreadsheet may be production. Test writes carefully.
 */

var SCRIPT_TOKEN = "CHANGE_ME_TO_LONG_RANDOM_SECRET";
var CALENDAR_SHEET = "Лист1";
var CATEGORY_COL = 1; // A
var ROOM_COL = 2; // B
var HEADER_ROW = 1;
var FIRST_DATA_ROW = 2;
var FIRST_DATE_COL = 3; // C

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || "{}");
    if (body.token !== SCRIPT_TOKEN) {
      return json_({ ok: false, error: "unauthorized" });
    }
    var action = body.action || "";
    if (action === "ping") {
      return json_({ ok: true, sheet: CALENDAR_SHEET, mode: "grid_ab_dates" });
    }
    if (action === "occupied") {
      return json_({
        ok: true,
        occupied_unit_ids: occupiedUnits_(
          body.date_from,
          body.date_to,
          body.exclude_booking_id || null
        ),
      });
    }
    if (action === "reserve") {
      var booking = body.booking || {};
      reserve_(booking);
      return json_({ ok: true, booking: booking });
    }
    if (action === "release") {
      release_(body.booking_id, body.unit_id || null);
      return json_({ ok: true });
    }
    if (action === "upsert") {
      var b = body.booking || {};
      var st = String(b.status || "").toUpperCase();
      if (["CANCELLED", "REJECTED", "EXPIRED", "OWNER_REJECTED"].indexOf(st) >= 0) {
        release_(b.external_id, b.unit_id || null);
      } else {
        reserve_(b);
      }
      return json_({ ok: true, booking: b });
    }
    if (action === "list") {
      return json_({ ok: true, bookings: listAsBookings_() });
    }
    return json_({ ok: false, error: "unknown_action" });
  } catch (err) {
    return json_({ ok: false, error: String(err && err.message ? err.message : err) });
  }
}

function doGet() {
  return json_({
    ok: true,
    service: "dobrolap-sheets-bridge",
    mode: "grid_ab_dates",
    hint: "POST actions: ping|occupied|reserve|release|upsert|list",
  });
}

function occupiedUnits_(dateFromStr, dateToStr, excludeBookingId) {
  var lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    var sh = calendarSheet_();
    var values = sh.getDataRange().getValues();
    var dateCols = dateColumns_(values[HEADER_ROW - 1] || [], dateFromStr, dateToStr);
    if (values.length < FIRST_DATA_ROW) return [];
    var rooms = roomRows_(values);
    var occupied = {};
    for (var i = 0; i < rooms.length; i++) {
      var r = rooms[i].row;
      var label = rooms[i].label;
      for (var j = 0; j < dateCols.length; j++) {
        var c = dateCols[j];
        if (isOccupiedCell_(values[r][c], excludeBookingId)) {
          occupied[label] = true;
          break;
        }
      }
    }
    return Object.keys(occupied);
  } finally {
    lock.releaseLock();
  }
}

function reserve_(booking) {
  var lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    var externalId = String(booking.external_id || "").trim();
    var unitId = String(booking.unit_id || "").trim();
    var dateFrom = String(booking.date_from || "").trim();
    var dateTo = String(booking.date_to || "").trim();
    var mark = String(booking.status || "HOLD") + ":" + externalId;
    if (!externalId || !unitId || !dateFrom || !dateTo) {
      throw new Error("reserve requires external_id, unit_id, date_from, date_to");
    }

    var sh = calendarSheet_();
    var values = sh.getDataRange().getValues();
    var rooms = roomRows_(values);
    var rowIndex = -1;
    var want = unitId.toLowerCase();
    for (var i = 0; i < rooms.length; i++) {
      if (String(rooms[i].label).toLowerCase() === want) {
        rowIndex = rooms[i].row;
        break;
      }
    }
    if (rowIndex < 0) {
      throw new Error("unknown_room:" + unitId);
    }
    var dateCols = dateColumns_(values[HEADER_ROW - 1], dateFrom, dateTo);
    if (!dateCols.length) {
      throw new Error("no_date_columns_for_range");
    }

    for (var k = 0; k < dateCols.length; k++) {
      var c = dateCols[k];
      if (isOccupiedCell_(values[rowIndex][c], externalId)) {
        throw new Error("unit_occupied");
      }
    }

    for (var j = 0; j < dateCols.length; j++) {
      sh.getRange(rowIndex + 1, dateCols[j] + 1).setValue(mark);
    }
  } finally {
    lock.releaseLock();
  }
}

function release_(bookingId, unitId) {
  var lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    var externalId = String(bookingId || "").trim();
    if (!externalId) return;
    var sh = calendarSheet_();
    var values = sh.getDataRange().getValues();
    var rooms = roomRows_(values);
    var want = unitId ? String(unitId).trim().toLowerCase() : null;
    for (var i = 0; i < rooms.length; i++) {
      var r = rooms[i].row;
      if (want && String(rooms[i].label).toLowerCase() !== want) continue;
      for (var c = FIRST_DATE_COL - 1; c < values[r].length; c++) {
        var cell = values[r][c];
        if (cell === "" || cell === null) continue;
        if (String(cell).indexOf(externalId) >= 0) {
          sh.getRange(r + 1, c + 1).clearContent();
        }
      }
    }
  } finally {
    lock.releaseLock();
  }
}

function listAsBookings_() {
  var sh = calendarSheet_();
  var values = sh.getDataRange().getValues();
  if (values.length < FIRST_DATA_ROW) return [];
  var headers = values[HEADER_ROW - 1];
  var rooms = roomRows_(values);
  var out = [];
  for (var i = 0; i < rooms.length; i++) {
    var r = rooms[i].row;
    var room = rooms[i].label;
    for (var c = FIRST_DATE_COL - 1; c < headers.length; c++) {
      var d = parseHeaderDate_(headers[c]);
      if (!d) continue;
      var cell = values[r][c];
      if (!isOccupiedCell_(cell, null)) continue;
      var id = extractBookingId_(cell) || "manual:" + room + ":" + formatYmd_(d);
      out.push({
        external_id: id,
        unit_id: room,
        date_from: formatYmd_(d),
        date_to: formatYmd_(nextDay_(d)),
        status: "CONFIRMED",
      });
    }
  }
  return out;
}

function calendarSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(CALENDAR_SHEET);
  if (!sh) {
    throw new Error("sheet_not_found:" + CALENDAR_SHEET);
  }
  return sh;
}

function roomRows_(values) {
  var out = [];
  var carried = "";
  for (var r = FIRST_DATA_ROW - 1; r < values.length; r++) {
    var cat = String(values[r][CATEGORY_COL - 1] || "").trim();
    var sub = String(values[r][ROOM_COL - 1] || "").trim();
    if (cat) carried = cat;
    var label = null;
    if (/^\d+$/.test(sub)) {
      var active = cat || carried;
      if (active) label = active + " " + sub;
    } else if (sub) {
      label = sub;
    } else if (cat) {
      label = cat;
    }
    if (label) out.push({ row: r, label: label });
  }
  return out;
}

function dateColumns_(headerRow, dateFromStr, dateToStr) {
  var from = parseYmd_(dateFromStr);
  var to = parseYmd_(dateToStr);
  var cols = [];
  var days = {};
  for (var c = FIRST_DATE_COL - 1; c < headerRow.length; c++) {
    var d = parseHeaderDate_(headerRow[c]);
    if (!d) continue;
    if (d.getTime() >= from.getTime() && d.getTime() < to.getTime()) {
      cols.push(c);
      days[d.getFullYear() + "-" + d.getMonth() + "-" + d.getDate()] = true;
    }
  }
  var expected = 0;
  for (var day = new Date(from.getTime()); day.getTime() < to.getTime(); day.setDate(day.getDate() + 1)) {
    expected++;
    if (!days[day.getFullYear() + "-" + day.getMonth() + "-" + day.getDate()]) {
      throw new Error("calendar_date_range_incomplete");
    }
  }
  if (!expected || cols.length !== expected) {
    throw new Error("calendar_date_range_incomplete");
  }
  return cols;
}

function isOccupiedCell_(cell, excludeBookingId) {
  if (cell === "" || cell === null) return false;
  var text = String(cell).trim();
  if (!text) return false;
  if (excludeBookingId && text.indexOf(String(excludeBookingId)) >= 0) return false;
  return true;
}

function extractBookingId_(cell) {
  if (cell === "" || cell === null) return null;
  var text = String(cell);
  var m = text.match(/(?:HOLD|WAITING_PAYMENT|CONFIRMED|OWNER_APPROVED):([A-Za-z0-9_-]+)/);
  if (m) return m[1];
  return null;
}

function parseHeaderDate_(value) {
  if (Object.prototype.toString.call(value) === "[object Date]" && !isNaN(value)) {
    return new Date(value.getFullYear(), value.getMonth(), value.getDate());
  }
  var text = String(value || "").trim();
  if (!text) return null;
  var ymd = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (ymd) return new Date(+ymd[1], +ymd[2] - 1, +ymd[3]);
  var dmy = text.match(/^(\d{1,2})[./](\d{1,2})[./](\d{2,4})$/);
  if (dmy) {
    var y = +dmy[3];
    if (y < 100) y += 2000;
    return new Date(y, +dmy[2] - 1, +dmy[1]);
  }
  return null;
}

function parseYmd_(text) {
  var d = parseHeaderDate_(text);
  if (!d) throw new Error("bad_date:" + text);
  return d;
}

function nextDay_(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1);
}

function formatYmd_(d) {
  return Utilities.formatDate(d, "UTC", "yyyy-MM-dd");
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
