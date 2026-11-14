// Read-only audit of an open InDesign document: page sizes, overset text, link status,
// placed-graphic scale and effective PPI, missing fonts, hidden / non-printing layers,
// placeholder text. Runs as the body of a function — pass it to the adobe-bundle
// InDesign `execute_extend_script` tool, or run scripts/run_indesign_audit.py.
// It only reads; the one preference it touches (script measurement unit) is restored.

var TARGET_DOC_NAME = "";
var MIN_PPI = 150;
var PLACEHOLDER = /\b(lorem|ipsum|placeholder|todo|tbd|xxx+)\b/i;

function round(value) { return Math.round(value * 1000) / 1000; }
function pageNameOf(item) {
  try { return item.parentPage ? item.parentPage.name : "pasteboard"; } catch (error) { return "unknown"; }
}

var doc = TARGET_DOC_NAME ? app.documents.itemByName(TARGET_DOC_NAME) : app.activeDocument;
if (!doc.isValid) throw Error("Document not open: " + TARGET_DOC_NAME);

var previousUnit = app.scriptPreferences.measurementUnit;
app.scriptPreferences.measurementUnit = MeasurementUnits.INCHES;
try {
  var report = {
    document: doc.name,
    path: doc.saved ? doc.fullName.fsName : null,
    unsavedChanges: doc.modified,
    pages: [], overset: [], placeholders: [], links: [], placedDrawings: [], images: [],
    missingFonts: [], hiddenLayers: [], nonPrintingLayers: [], attention: []
  };

  for (var p = 0; p < doc.pages.length; p++) {
    var bounds = doc.pages[p].bounds;
    report.pages.push({ name: doc.pages[p].name, widthIn: round(bounds[3] - bounds[1]), heightIn: round(bounds[2] - bounds[0]) });
  }

  for (var s = 0; s < doc.stories.length; s++) {
    var story = doc.stories[s];
    var containers = story.textContainers;
    var lastFrame = containers.length ? containers[containers.length - 1] : null;
    var excerpt = String(story.contents).substr(0, 80);
    if (story.overflows) report.overset.push({ storyId: story.id, page: lastFrame ? pageNameOf(lastFrame) : "none", text: excerpt });
    if (PLACEHOLDER.test(story.contents)) report.placeholders.push({ storyId: story.id, page: lastFrame ? pageNameOf(lastFrame) : "none", text: excerpt });
  }

  for (var l = 0; l < doc.links.length; l++) {
    var link = doc.links[l];
    var linkPage = "unknown";
    try { linkPage = pageNameOf(link.parent); } catch (error) {}
    report.links.push({ name: link.name, path: link.filePath, status: String(link.status), page: linkPage, ok: link.status === LinkStatus.NORMAL });
  }

  for (var g = 0; g < doc.allGraphics.length; g++) {
    var graphic = doc.allGraphics[g];
    var kind = graphic.constructor.name;
    var entry = {
      kind: kind,
      link: graphic.itemLink && graphic.itemLink.isValid ? graphic.itemLink.name : "(embedded or pasted)",
      page: pageNameOf(graphic),
      scalePercent: [round(graphic.horizontalScale), round(graphic.verticalScale)]
    };
    if (kind === "Image") {
      try { entry.effectivePpi = graphic.effectivePpi; entry.lowPpi = Math.min(entry.effectivePpi[0], entry.effectivePpi[1]) < MIN_PPI; } catch (error) {}
      report.images.push(entry);
    } else {
      entry.notAt100 = Math.abs(graphic.horizontalScale - 100) > 0.01 || Math.abs(graphic.verticalScale - 100) > 0.01;
      report.placedDrawings.push(entry);
    }
  }

  for (var f = 0; f < doc.fonts.length; f++) {
    if (doc.fonts[f].status !== FontStatus.INSTALLED) report.missingFonts.push({ name: doc.fonts[f].name, status: String(doc.fonts[f].status) });
  }

  for (var y = 0; y < doc.layers.length; y++) {
    if (!doc.layers[y].visible) report.hiddenLayers.push(doc.layers[y].name);
    if (!doc.layers[y].printable) report.nonPrintingLayers.push(doc.layers[y].name);
  }

  var brokenLinks = 0, lowPpi = 0, scaledDrawings = 0;
  for (var a = 0; a < report.links.length; a++) if (!report.links[a].ok) brokenLinks++;
  for (var b = 0; b < report.images.length; b++) if (report.images[b].lowPpi) lowPpi++;
  for (var c = 0; c < report.placedDrawings.length; c++) if (report.placedDrawings[c].notAt100) scaledDrawings++;
  if (report.overset.length) report.attention.push(report.overset.length + " overset stor(ies)");
  if (brokenLinks) report.attention.push(brokenLinks + " link(s) not NORMAL");
  if (lowPpi) report.attention.push(lowPpi + " image(s) below " + MIN_PPI + " ppi");
  if (scaledDrawings) report.attention.push(scaledDrawings + " placed drawing(s) not at 100% — check stated drawing scale");
  if (report.missingFonts.length) report.attention.push(report.missingFonts.length + " missing font(s)");
  if (report.placeholders.length) report.attention.push(report.placeholders.length + " stor(ies) with placeholder text");
  if (report.hiddenLayers.length) report.attention.push("hidden layers will not export: " + report.hiddenLayers.join(", "));
  if (report.unsavedChanges) report.attention.push("document has unsaved changes — the PDF may not match the INDD");
} finally {
  app.scriptPreferences.measurementUnit = previousUnit;
}
return report;
