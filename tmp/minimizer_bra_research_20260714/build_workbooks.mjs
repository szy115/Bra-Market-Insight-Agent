import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const here = path.dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(await fs.readFile(path.join(here, "workbook_data.json"), "utf8"));
const outputDir = "C:/Users/HSIA/Downloads/amazon_sample_painpoint_minimizer_bra_20260714";
const previewDir = path.join(here, "previews");
await fs.mkdir(outputDir, { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const COLORS = {
  ink: "#143F3C",
  teal: "#2F7F7A",
  tealLight: "#DDECEA",
  tealPale: "#F2F8F7",
  coral: "#B7535F",
  coralLight: "#F7E8EA",
  sand: "#EFE6DA",
  gold: "#C89958",
  white: "#FFFFFF",
  text: "#233634",
  muted: "#5F7471",
  grid: "#CBDAD8",
  gray: "#F3F5F5",
};

const moneyFmt = "$#,##0.00";
const intFmt = "#,##0";
const pctFmt = "0.0%";

function asDate(ms) {
  return ms ? new Date(ms) : null;
}

function textList(value) {
  return Array.isArray(value) ? value.join("、") : (value ?? "");
}

function titleBlock(sheet, lastCol, title, subtitle) {
  sheet.showGridLines = false;
  sheet.getRange(`A1:${lastCol}1`).merge();
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A2:${lastCol}2`).merge();
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A1:${lastCol}1`).format = {
    fill: COLORS.ink,
    font: { bold: true, color: COLORS.white, size: 20 },
    verticalAlignment: "center",
  };
  sheet.getRange(`A2:${lastCol}2`).format = {
    fill: COLORS.tealLight,
    font: { color: COLORS.ink, size: 10 },
    verticalAlignment: "center",
    wrapText: true,
  };
  sheet.getRange("A1").format.rowHeight = 34;
  sheet.getRange("A2").format.rowHeight = 30;
}

function section(sheet, range, text) {
  const r = sheet.getRange(range);
  r.merge();
  r.values = [[text]];
  r.format = {
    fill: COLORS.teal,
    font: { bold: true, color: COLORS.white, size: 12 },
    verticalAlignment: "center",
  };
  r.format.rowHeight = 24;
}

function header(range) {
  range.format = {
    fill: COLORS.ink,
    font: { bold: true, color: COLORS.white, size: 10 },
    borders: { preset: "all", style: "thin", color: COLORS.grid },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
  };
  range.format.rowHeight = 30;
}

function body(range) {
  range.format = {
    font: { color: COLORS.text, size: 9 },
    borders: { preset: "all", style: "thin", color: COLORS.grid },
    verticalAlignment: "top",
    wrapText: true,
  };
}

function setColumnWidths(sheet, specs, rowEnd = 200) {
  for (const [col, width] of specs) {
    sheet.getRange(`${col}1:${col}${rowEnd}`).format.columnWidth = width;
  }
}

function addNote(sheet, range, note) {
  const r = sheet.getRange(range);
  r.merge();
  r.values = [[note]];
  r.format = {
    fill: COLORS.sand,
    font: { color: COLORS.text, italic: true, size: 9 },
    borders: { preset: "outside", style: "thin", color: COLORS.gold },
    verticalAlignment: "center",
    wrapText: true,
  };
}

function scanFormulaErrors(workbook, workbookName) {
  const errors = [];
  const pattern = /#(?:REF!|DIV\/0!|VALUE!|NAME\?|N\/A|NUM!|NULL!)/i;
  for (const sheet of workbook.worksheets.items) {
    const used = sheet.getUsedRange();
    const values = used?.values ?? [];
    values.forEach((row, r) => row.forEach((value, c) => {
      if (typeof value === "string" && pattern.test(value)) {
        errors.push(`${sheet.name}!R${r + 1}C${c + 1}: ${value}`);
      }
    }));
  }
  if (errors.length) throw new Error(`${workbookName} formula errors:\n${errors.join("\n")}`);
  return `${workbookName}: no formula errors found`;
}

async function renderAll(workbook, prefix) {
  const files = [];
  for (const sheet of workbook.worksheets.items) {
    const blob = await workbook.render({
      sheetName: sheet.name,
      autoCrop: "all",
      scale: 0.8,
      format: "png",
    });
    const safeName = sheet.name.replace(/[\\/:*?"<>|]/g, "_");
    const out = path.join(previewDir, `${prefix}_${safeName}.png`);
    await fs.writeFile(out, new Uint8Array(await blob.arrayBuffer()));
    files.push(out);
  }
  return files;
}

async function buildSamplesWorkbook() {
  const wb = Workbook.create();
  const overview = wb.worksheets.add("样本概览");
  const samples = wb.worksheets.add("产品样本");
  const source = wb.worksheets.add("来源说明");

  titleBlock(
    overview,
    "J",
    "美国站 Minimizer Bra｜Amazon 样本概览",
    `SellerSprite MCP｜Amazon US｜数据月 ${data.metadata.amazonMonth}｜样本按 parent ASIN 去重｜研究日 ${data.metadata.researchDate}`,
  );

  const metricLabels = [["去重样本"], ["样本月销量"], ["样本月销售额"], ["价格中位数"], ["平均评分"]];
  const metricCells = ["B5", "D5", "F5", "H5", "J5"];
  const labelCells = ["A5", "C5", "E5", "G5", "I5"];
  metricLabels.forEach((v, i) => {
    overview.getRange(labelCells[i]).values = [v];
    overview.getRange(labelCells[i]).format = {
      fill: COLORS.tealLight,
      font: { bold: true, color: COLORS.ink },
      horizontalAlignment: "center",
      verticalAlignment: "center",
      borders: { preset: "all", style: "thin", color: COLORS.grid },
      wrapText: true,
    };
    overview.getRange(metricCells[i]).format = {
      fill: COLORS.white,
      font: { bold: true, color: COLORS.coral, size: 15 },
      horizontalAlignment: "center",
      verticalAlignment: "center",
      borders: { preset: "all", style: "thin", color: COLORS.grid },
    };
  });
  overview.getRange("B5").formulas = [["=COUNTA('产品样本'!B2:B51)"]];
  overview.getRange("D5").formulas = [["=SUM('产品样本'!I2:I51)"]];
  overview.getRange("F5").formulas = [["=SUM('产品样本'!J2:J51)"]];
  overview.getRange("H5").formulas = [["=MEDIAN('产品样本'!F2:F51)"]];
  overview.getRange("J5").formulas = [["=AVERAGE('产品样本'!G2:G51)"]];
  overview.getRange("D5").format.numberFormat = intFmt;
  overview.getRange("F5").format.numberFormat = "$#,##0";
  overview.getRange("H5").format.numberFormat = moneyFmt;
  overview.getRange("J5").format.numberFormat = "0.00";
  overview.getRange("A5:J5").format.rowHeight = 42;

  section(overview, "A8:E8", "样本月销量 Top 10 品牌");
  section(overview, "G8:J8", "结构线索覆盖");
  overview.getRange("A9:B19").values = [["品牌", "样本月销量"], ...data.sampleSummary.top_brands];
  overview.getRange("G9:H20").values = [["结构线索", "样本数"], ...data.sampleSummary.structure_counts];
  header(overview.getRange("A9:B9"));
  header(overview.getRange("G9:H9"));
  body(overview.getRange("A10:B19"));
  body(overview.getRange("G10:H20"));
  overview.getRange("B10:B19").format.numberFormat = intFmt;
  overview.getRange("H10:H20").format.numberFormat = intFmt;

  section(overview, "A22:J22", "研发判断");
  overview.getRange("A23:J27").values = [
    ["1", "成熟且集中", "Bali 与 Vanity Fair 两个品牌合计贡献样本月销量约57.3%，新品不宜以“基础缩胸”单点切入。", null, null, null, null, null, null, null],
    ["2", "主流结构清晰", "全罩杯、轻薄无衬垫、有钢圈/无钢圈两条路线均已成熟；真正可拉开差距的是分离度、凉感遮点、耐洗与分杯段级放。", null, null, null, null, null, null, null],
    ["3", "机会点不足", "50个样本中，仅2个标题明确强调背部/侧比平整，体态支撑仅1个；但需结合评论验证，不可仅凭标题判断空白。", null, null, null, null, null, null, null],
    ["4", "建议价位", `样本价格中位数为 $${data.sampleSummary.median_price.toFixed(2)}；研发首发建议零售价 $29.99–34.99，以结构升级支撑溢价。`, null, null, null, null, null, null, null],
    ["5", "数据边界", "月销量与销售额为 SellerSprite 估算；款式结构由标题/关键词提取，材质与尺码必须回到商品详情页复核。", null, null, null, null, null, null, null],
  ];
  for (let r = 23; r <= 27; r++) overview.getRange(`C${r}:J${r}`).merge();
  body(overview.getRange("A23:J27"));
  overview.getRange("A23:A27").format = { fill: COLORS.coralLight, font: { bold: true, color: COLORS.coral }, horizontalAlignment: "center", verticalAlignment: "center", borders: { preset: "all", style: "thin", color: COLORS.grid } };
  overview.getRange("B23:B27").format = { fill: COLORS.tealPale, font: { bold: true, color: COLORS.ink }, verticalAlignment: "center", borders: { preset: "all", style: "thin", color: COLORS.grid }, wrapText: true };
  overview.getRange("A23:J27").format.rowHeight = 42;
  addNote(overview, "A30:J32", "口径：这是围绕美国站 minimizer bra 的方向性样本库，并非完整类目审计。样本从多个关键词组抓取后按 parent ASIN 去重；每个商品保留 Amazon 链接、匹配理由与 SellerSprite 数据边界。详情见“产品样本”和“来源说明”。");
  setColumnWidths(overview, [["A", 12], ["B", 17], ["C", 12], ["D", 17], ["E", 12], ["F", 17], ["G", 18], ["H", 17], ["I", 12], ["J", 17]], 40);
  overview.freezePanes.freezeRows(2);

  samples.showGridLines = false;
  const sampleHeaders = ["No.", "ASIN", "Amazon URL", "商品标题", "品牌", "价格", "评分", "评论数", "月销量", "月销售额", "变体数", "BSR", "上架日期", "配送", "卖家", "结构线索", "主分组", "匹配理由", "数据说明"];
  samples.getRange("A1:S1").values = [sampleHeaders];
  const sampleRows = data.samples.map((s, i) => [
    i + 1,
    s.asin,
    s.amazonUrl,
    s.title,
    s.brand,
    s.price,
    s.rating,
    s.ratings,
    s.units,
    s.revenue,
    s.variations,
    s.bsr,
    asDate(s.availableDate),
    s.fulfillment,
    s.sellerName,
    textList(s.structureClues),
    s.primaryGroup,
    s.matchReason,
    s.sourceNote,
  ]);
  samples.getRange(`A2:S${sampleRows.length + 1}`).values = sampleRows;
  header(samples.getRange("A1:S1"));
  body(samples.getRange(`A2:S${sampleRows.length + 1}`));
  samples.getRange(`F2:F${sampleRows.length + 1}`).format.numberFormat = moneyFmt;
  samples.getRange(`G2:G${sampleRows.length + 1}`).format.numberFormat = "0.0";
  samples.getRange(`H2:L${sampleRows.length + 1}`).format.numberFormat = intFmt;
  samples.getRange(`J2:J${sampleRows.length + 1}`).format.numberFormat = moneyFmt;
  samples.getRange(`M2:M${sampleRows.length + 1}`).format.numberFormat = "yyyy-mm-dd";
  samples.getRange(`A2:A${sampleRows.length + 1}`).format.horizontalAlignment = "center";
  samples.getRange(`B2:B${sampleRows.length + 1}`).format.font = { color: COLORS.teal, bold: true, size: 9 };
  samples.getRange(`C2:C${sampleRows.length + 1}`).format.font = { color: "#1D5B8F", underline: true, size: 8 };
  samples.getRange(`A2:S${sampleRows.length + 1}`).format.rowHeight = 42;
  samples.tables.add(`A1:S${sampleRows.length + 1}`, true, "AmazonMinimizerSamples");
  samples.freezePanes.freezeRows(1);
  samples.freezePanes.freezeColumns(5);
  setColumnWidths(samples, [["A", 6], ["B", 13], ["C", 30], ["D", 52], ["E", 17], ["F", 11], ["G", 8], ["H", 12], ["I", 12], ["J", 15], ["K", 10], ["L", 9], ["M", 13], ["N", 10], ["O", 18], ["P", 28], ["Q", 16], ["R", 46], ["S", 40]], 55);

  titleBlock(source, "H", "数据来源与研究口径", "用于复核样本选择逻辑、关键词覆盖与数据边界");
  section(source, "A5:H5", "基础口径");
  const baseRows = [
    ["目标站点", "Amazon US", "数据工具", "SellerSprite MCP", "数据月", data.metadata.amazonMonth, "研究日期", data.metadata.researchDate],
    ["类目", data.metadata.amazonNode, "节点路径", "7141123011:7147440011:1040660:9522931011:14333511:1044960:1045002", "类目商品数", 538, "去重样本", data.metadata.amazonSampleCount],
  ];
  source.getRange("A6:H7").values = baseRows;
  body(source.getRange("A6:H7"));
  source.getRange("A6:H7").format.rowHeight = 38;
  source.getRange("A6:H7").getColumn(0).format.font = { bold: true, color: COLORS.ink };

  section(source, "A10:H10", "检索关键词组");
  const groups = [
    ["核心缩胸", "minimizer bra", "用于抓取类目核心畅销款"],
    ["全罩杯", "full coverage minimizer bra", "关注包覆与溢出控制"],
    ["大码", "plus size minimizer bra", "覆盖DDD–I杯与大底围"],
    ["无钢圈", "wireless minimizer bra", "关注舒适、支撑与uniboob风险"],
    ["背部平整", "back smoothing minimizer bra", "关注侧比/U背与背部勒痕"],
    ["无肩带", "strapless minimizer bra", "关注防滑、稳定与礼服场景"],
    ["轻薄", "unlined minimizer bra", "关注透气、遮点与T恤隐形"],
  ];
  source.getRange("A11:C18").values = [["方向", "关键词", "研发用途"], ...groups];
  header(source.getRange("A11:C11"));
  body(source.getRange("A12:C18"));
  source.getRange("A12:C18").format.rowHeight = 34;

  section(source, "A21:H21", "方法与限制");
  source.getRange("A22:H27").values = [
    ["去重", "按 parent ASIN 去重，避免同一款不同子体重复占位。", null, null, null, null, null, null],
    ["匹配", "结合标题、关键词组和结构线索判断研发参考价值；不把标题缺失当作结构缺失。", null, null, null, null, null, null],
    ["销量", "月销量、销售额、BSR与评论增量为 SellerSprite 估算值，不等同于 Amazon 官方结算。", null, null, null, null, null, null],
    ["尺码/材质", "标题不足以确认面料克重、钢圈规格、杯容与尺码表，进入打样前必须回到详情页与实物复核。", null, null, null, null, null, null],
    ["适用范围", "用于设计方向锚定和竞品样本筛选，不替代完整市场容量、利润与专利/FTO分析。", null, null, null, null, null, null],
    ["链接", "产品样本表保留每个 ASIN 的 Amazon URL，便于设计师逐款查看主图、买家返图和Listing。", null, null, null, null, null, null],
  ];
  for (let r = 22; r <= 27; r++) source.getRange(`B${r}:H${r}`).merge();
  body(source.getRange("A22:H27"));
  source.getRange("A22:A27").format = { fill: COLORS.tealPale, font: { bold: true, color: COLORS.ink }, borders: { preset: "all", style: "thin", color: COLORS.grid }, verticalAlignment: "center" };
  source.getRange("A22:H27").format.rowHeight = 42;
  setColumnWidths(source, [["A", 16], ["B", 36], ["C", 36], ["D", 18], ["E", 16], ["F", 18], ["G", 16], ["H", 20]], 35);
  source.freezePanes.freezeRows(2);

  const inspect = await wb.inspect({ kind: "region", sheetId: "样本概览", range: "A1:J32", maxChars: 3500 });
  return { wb, inspect: inspect.ndjson ?? String(inspect) };
}

async function buildPainWorkbook() {
  const wb = Workbook.create();
  const overview = wb.worksheets.add("结论总览");
  const matrix = wb.worksheets.add("Pain Matrix");
  const directions = wb.worksheets.add("Design Directions");
  const tiktok = wb.worksheets.add("TikTok Evidence");
  const trends = wb.worksheets.add("Trend Sources");
  const reviews = wb.worksheets.add("Review Scope");
  const spec = wb.worksheets.add("Design Spec");

  titleBlock(overview, "N", "美国站 Minimizer Bra｜痛点到研发定义", `Amazon 评论 ${data.metadata.amazonNegativeReviews + data.metadata.amazonPositiveReviews} 条｜TikTok Shop 产品 ${data.metadata.tiktokProducts} 个｜研究日 ${data.metadata.researchDate}`);
  section(overview, "A5:G5", "首发概念");
  overview.getRange("A6:G11").values = [
    ["概念名", data.designSpec.conceptName, null, null, null, null, null],
    ["目标用户", data.designSpec.targetUser, null, null, null, null, null],
    ["首发尺码", data.designSpec.firstLaunchSizes, null, null, null, null, null],
    ["建议零售价", data.designSpec.targetRetail, null, null, null, null, null],
    ["核心承诺", data.designSpec.corePromise, null, null, null, null, null],
    ["核心结构", data.designSpec.coreStructure, null, null, null, null, null],
  ];
  for (let r = 6; r <= 11; r++) overview.getRange(`B${r}:G${r}`).merge();
  body(overview.getRange("A6:G11"));
  overview.getRange("A6:A11").format = { fill: COLORS.tealPale, font: { bold: true, color: COLORS.ink }, borders: { preset: "all", style: "thin", color: COLORS.grid }, verticalAlignment: "center" };
  overview.getRange("A6:G11").format.rowHeight = 42;

  section(overview, "A14:G14", "最高优先级研发任务");
  const topDirections = data.designDirections.slice(0, 5).map(d => [d.priority, d.theme, d.feature, d.why, d.validation, null, null]);
  overview.getRange("A15:G20").values = [["优先级", "方向", "结构定义", "为何做", "验证重点", null, null], ...topDirections];
  overview.getRange("E15:G15").merge();
  for (let r = 16; r <= 20; r++) overview.getRange(`E${r}:G${r}`).merge();
  header(overview.getRange("A15:G15"));
  body(overview.getRange("A16:G20"));
  overview.getRange("A16:A20").format = { fill: COLORS.coralLight, font: { bold: true, color: COLORS.coral }, horizontalAlignment: "center", verticalAlignment: "center", borders: { preset: "all", style: "thin", color: COLORS.grid } };
  overview.getRange("A16:G20").format.rowHeight = 52;

  section(overview, "A23:G23", "必须保留的消费者正向价值");
  overview.getRange("A24:G27").values = [
    ["舒适", "正向评论中23/40涉及舒适；不可为了缩胸牺牲全天穿着。", null, null, null, null, null],
    ["合体", "17/40涉及合体；尺码分段与公差管理是基础能力。", null, null, null, null, null],
    ["支撑与分离", "13/40涉及支撑，部分用户明确在意不形成uniboob。", null, null, null, null, null],
    ["包覆/平整", "11/40涉及覆盖和平整，是穿T恤与衬衫时最可见的结果。", null, null, null, null, null],
  ];
  for (let r = 24; r <= 27; r++) overview.getRange(`B${r}:G${r}`).merge();
  body(overview.getRange("A24:G27"));
  overview.getRange("A24:A27").format = { fill: COLORS.tealPale, font: { bold: true, color: COLORS.ink }, borders: { preset: "all", style: "thin", color: COLORS.grid }, verticalAlignment: "center" };
  overview.getRange("A24:G27").format.rowHeight = 38;

  section(overview, "I5:N5", "结构规格卡｜AirSculpt Cool Minimizer");
  const blueprintCards = [
    [6, 7, "杯型结构", "三片式全罩杯＋内侧托片＋稳定鸡心；减少侧向投影，保留自然分离。"],
    [9, 10, "凉感遮点", "外层轻量稳定网布＋内层吸湿针织；仅在乳点区做超薄遮点。"],
    [12, 13, "侧背/肩带", "高侧比渐进弹力Power Mesh；C–F杯18mm肩带，G–I杯22mm。"],
    [15, 16, "版型级放", "34C–46I；按C–DD / DDD–G / H–I三段独立杯容、底围与肩带级放。"],
    [18, 19, "颜色系统", "Warm Sand / Caramel / Cocoa / Espresso / Black；季节色Teal / Berry / Purple。"],
    [21, 23, "验证与宣称", "1–1.5杯仅作研发目标；凉感、不滑、不勒与缩胸效果需完成试穿、洗护和材料测试后再用于营销。"],
  ];
  for (const [start, end, label, value] of blueprintCards) {
    overview.getRange(`I${start}:J${end}`).merge();
    overview.getRange(`I${start}`).values = [[label]];
    overview.getRange(`K${start}:N${end}`).merge();
    overview.getRange(`K${start}`).values = [[value]];
    overview.getRange(`I${start}:J${end}`).format = { fill: COLORS.tealPale, font: { bold: true, color: COLORS.ink }, borders: { preset: "all", style: "thin", color: COLORS.grid }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
    overview.getRange(`K${start}:N${end}`).format = { fill: COLORS.white, font: { color: COLORS.text, size: 9 }, borders: { preset: "all", style: "thin", color: COLORS.grid }, verticalAlignment: "center", wrapText: true };
  }
  addNote(overview, "I25:N28", "完整结构图另附高清 PNG 与可编辑 SVG：前片、后片、结构标注、肩带分段与颜色计划均已出图。该图为研发沟通概念，不是最终纸样。");
  addNote(overview, "A30:N33", `数据边界：${data.metadata.agentReachStatus} Amazon 评论按1–3星归为负向、4–5星归为正向；关键词辅助聚类可重叠。FastMoss 近28天数据截至2026-07-13，头部视频多为广告放大，不能直接等同自然爆款。`);
  setColumnWidths(overview, [["A", 10], ["B", 18], ["C", 22], ["D", 24], ["E", 22], ["F", 14], ["G", 14], ["H", 3], ["I", 14], ["J", 14], ["K", 14], ["L", 14], ["M", 14], ["N", 14]], 36);
  overview.freezePanes.freezeRows(2);

  matrix.showGridLines = false;
  const painHeaders = ["优先级", "痛点", "评论命中", "负向样本基数", "命中率", "严重度(1–5)", "来源覆盖(1–3)", "优先分", "主要影响", "失效机制", "研发方案", "验证方式", "代表ASIN", "口径说明"];
  matrix.getRange("A1:N1").values = [painHeaders];
  const painRows = data.painMatrix.map(p => [p.priority, p.painPoint, p.reviewHits, p.sampleBase, null, p.severity, p.sourceCoverage, null, p.affected, p.mechanism, p.solution, p.validation, p.representativeAsins, p.caveat]);
  matrix.getRange(`A2:N${painRows.length + 1}`).values = painRows;
  for (let r = 2; r <= painRows.length + 1; r++) {
    matrix.getRange(`E${r}`).formulas = [[`=C${r}/D${r}`]];
    matrix.getRange(`H${r}`).formulas = [[`=E${r}*F${r}*G${r}`]];
  }
  header(matrix.getRange("A1:N1"));
  body(matrix.getRange(`A2:N${painRows.length + 1}`));
  matrix.getRange(`E2:E${painRows.length + 1}`).format.numberFormat = pctFmt;
  matrix.getRange(`H2:H${painRows.length + 1}`).format.numberFormat = "0.00";
  matrix.getRange(`A2:A${painRows.length + 1}`).format = { fill: COLORS.coralLight, font: { bold: true, color: COLORS.coral }, horizontalAlignment: "center", verticalAlignment: "center", borders: { preset: "all", style: "thin", color: COLORS.grid } };
  matrix.getRange(`A2:N${painRows.length + 1}`).format.rowHeight = 66;
  matrix.getRange(`H2:H${painRows.length + 1}`).conditionalFormats.add("dataBar", { color: COLORS.coral, gradient: true });
  matrix.tables.add(`A1:N${painRows.length + 1}`, true, "PainPointMatrix");
  matrix.freezePanes.freezeRows(1);
  matrix.freezePanes.freezeColumns(2);
  setColumnWidths(matrix, [["A", 9], ["B", 26], ["C", 11], ["D", 13], ["E", 10], ["F", 11], ["G", 12], ["H", 11], ["I", 24], ["J", 42], ["K", 46], ["L", 40], ["M", 34], ["N", 28]], 15);

  directions.showGridLines = false;
  directions.getRange("A1:E1").values = [["优先级", "研发主题", "结构/功能定义", "证据逻辑", "验证重点"]];
  const directionRows = data.designDirections.map(d => [d.priority, d.theme, d.feature, d.why, d.validation]);
  directions.getRange(`A2:E${directionRows.length + 1}`).values = directionRows;
  header(directions.getRange("A1:E1"));
  body(directions.getRange(`A2:E${directionRows.length + 1}`));
  directions.getRange(`A2:A${directionRows.length + 1}`).format = { fill: COLORS.coralLight, font: { bold: true, color: COLORS.coral }, horizontalAlignment: "center", verticalAlignment: "center", borders: { preset: "all", style: "thin", color: COLORS.grid } };
  directions.getRange(`A2:E${directionRows.length + 1}`).format.rowHeight = 64;
  directions.tables.add(`A1:E${directionRows.length + 1}`, true, "DesignDirections");
  directions.freezePanes.freezeRows(1);
  setColumnWidths(directions, [["A", 9], ["B", 27], ["C", 42], ["D", 44], ["E", 42]], 15);

  tiktok.showGridLines = false;
  const ttHeaders = ["产品", "FastMoss产品URL", "价格区间", "评分", "评论数", "近28天GMV", "近28天销量", "关联达人", "关联视频", "广告占比", "联盟占比", "视频占比", "头部视频URL", "头部达人", "达人URL", "视频播放", "视频GMV", "是否广告", "Caption", "内容结构推断", "口径说明"];
  tiktok.getRange("A1:U1").values = [ttHeaders];
  const ttRows = data.tiktokEvidence.map(t => [
    t.product, t.productUrl, `$${t.priceMin.toFixed(2)}–$${t.priceMax.toFixed(2)}`, t.rating, t.reviewCount, t.l28Gmv, t.l28Units, t.l28Creators, t.l28Videos, t.adShare / 100, t.affiliateShare / 100, t.videoShare / 100, t.topVideoUrl, t.topCreator, t.topCreatorUrl, t.topVideoPlays, t.topVideoGmv, t.topVideoIsAd ? "是" : "否", t.topVideoCaption, t.contentInference, t.caveat,
  ]);
  tiktok.getRange(`A2:U${ttRows.length + 1}`).values = ttRows;
  header(tiktok.getRange("A1:U1"));
  body(tiktok.getRange(`A2:U${ttRows.length + 1}`));
  tiktok.getRange(`F2:G${ttRows.length + 1}`).format.numberFormat = moneyFmt;
  tiktok.getRange(`E2:I${ttRows.length + 1}`).format.numberFormat = intFmt;
  tiktok.getRange(`J2:L${ttRows.length + 1}`).format.numberFormat = pctFmt;
  tiktok.getRange(`P2:P${ttRows.length + 1}`).format.numberFormat = intFmt;
  tiktok.getRange(`Q2:Q${ttRows.length + 1}`).format.numberFormat = moneyFmt;
  for (const col of ["B", "M", "O"]) tiktok.getRange(`${col}2:${col}${ttRows.length + 1}`).format.font = { color: "#1D5B8F", underline: true, size: 8 };
  tiktok.getRange(`A2:U${ttRows.length + 1}`).format.rowHeight = 96;
  tiktok.tables.add(`A1:U${ttRows.length + 1}`, true, "TikTokEvidence");
  tiktok.freezePanes.freezeRows(1);
  tiktok.freezePanes.freezeColumns(2);
  setColumnWidths(tiktok, [["A", 24], ["B", 36], ["C", 16], ["D", 8], ["E", 11], ["F", 15], ["G", 13], ["H", 11], ["I", 11], ["J", 11], ["K", 11], ["L", 11], ["M", 38], ["N", 20], ["O", 38], ["P", 13], ["Q", 14], ["R", 10], ["S", 48], ["T", 42], ["U", 46]], 8);

  trends.showGridLines = false;
  trends.getRange("A1:F1").values = [["平台", "主题", "公开趋势洞察", "对缩胸文胸的启示", "来源URL", "边界"]];
  const trendRows = data.trendSources.map(t => [t.platform, t.theme, t.insight, t.implication, t.url, t.caveat]);
  trends.getRange(`A2:F${trendRows.length + 1}`).values = trendRows;
  header(trends.getRange("A1:F1"));
  body(trends.getRange(`A2:F${trendRows.length + 1}`));
  trends.getRange(`E2:E${trendRows.length + 1}`).format.font = { color: "#1D5B8F", underline: true, size: 8 };
  trends.getRange(`A2:F${trendRows.length + 1}`).format.rowHeight = 64;
  trends.tables.add(`A1:F${trendRows.length + 1}`, true, "TrendSources");
  trends.freezePanes.freezeRows(1);
  setColumnWidths(trends, [["A", 17], ["B", 29], ["C", 48], ["D", 46], ["E", 52], ["F", 32]], 20);

  reviews.showGridLines = false;
  reviews.getRange("A1:G1").values = [["ASIN", "代表产品", "负向评论(1–3星)", "正向评论(4–5星)", "合计", "Amazon URL", "用途"]];
  const reviewRows = data.reviewScope.map(r => [r.asin, r.name, r.negative, r.positive, null, `https://www.amazon.com/dp/${r.asin}`, "痛点与正向价值提取"]);
  reviews.getRange(`A2:G${reviewRows.length + 1}`).values = reviewRows;
  for (let r = 2; r <= reviewRows.length + 1; r++) reviews.getRange(`E${r}`).formulas = [[`=C${r}+D${r}`]];
  const totalRow = reviewRows.length + 3;
  reviews.getRange(`A${totalRow}:B${totalRow}`).merge();
  reviews.getRange(`A${totalRow}`).values = [["已获取评论合计"]];
  reviews.getRange(`C${totalRow}`).formulas = [[`=SUM(C2:C${reviewRows.length + 1})`]];
  reviews.getRange(`D${totalRow}`).formulas = [[`=SUM(D2:D${reviewRows.length + 1})`]];
  reviews.getRange(`E${totalRow}`).formulas = [[`=SUM(E2:E${reviewRows.length + 1})`]];
  reviews.getRange(`F${totalRow}:G${totalRow}`).merge();
  reviews.getRange(`F${totalRow}`).values = [["关键词辅助聚类，类别可重叠"]];
  header(reviews.getRange("A1:G1"));
  body(reviews.getRange(`A2:G${reviewRows.length + 1}`));
  reviews.getRange(`A${totalRow}:G${totalRow}`).format = { fill: COLORS.tealLight, font: { bold: true, color: COLORS.ink }, borders: { preset: "all", style: "thin", color: COLORS.grid }, verticalAlignment: "center", wrapText: true };
  reviews.getRange(`F2:F${reviewRows.length + 1}`).format.font = { color: "#1D5B8F", underline: true, size: 8 };
  reviews.getRange(`A2:G${reviewRows.length + 1}`).format.rowHeight = 42;
  reviews.freezePanes.freezeRows(1);
  setColumnWidths(reviews, [["A", 14], ["B", 30], ["C", 16], ["D", 16], ["E", 11], ["F", 42], ["G", 28]], 20);

  titleBlock(spec, "H", "AirSculpt Cool Minimizer｜设计定义", "从消费者痛点、Amazon样本、TikTok内容与公开趋势交叉形成；需经打样验证后才能转为营销宣称");
  section(spec, "A5:H5", "产品定义");
  const specRows = [
    ["概念名", data.designSpec.conceptName],
    ["目标用户", data.designSpec.targetUser],
    ["首发尺码", data.designSpec.firstLaunchSizes],
    ["建议零售价", data.designSpec.targetRetail],
    ["核心承诺", data.designSpec.corePromise],
    ["核心结构", data.designSpec.coreStructure],
    ["材料方向", data.designSpec.materials],
    ["色彩计划", data.designSpec.colorPlan],
    ["不可直接宣称", data.designSpec.notClaims],
  ];
  const startRow = 6;
  specRows.forEach((row, i) => {
    const r = startRow + i;
    spec.getRange(`A${r}`).values = [[row[0]]];
    spec.getRange(`B${r}:H${r}`).merge();
    spec.getRange(`B${r}`).values = [[row[1]]];
  });
  body(spec.getRange(`A${startRow}:H${startRow + specRows.length - 1}`));
  spec.getRange(`A${startRow}:A${startRow + specRows.length - 1}`).format = { fill: COLORS.tealPale, font: { bold: true, color: COLORS.ink }, borders: { preset: "all", style: "thin", color: COLORS.grid }, verticalAlignment: "center" };
  spec.getRange(`A${startRow}:H${startRow + specRows.length - 1}`).format.rowHeight = 50;
  section(spec, "A17:H17", "建议验证门槛");
  const validationRows = [
    ["版型", "C–DD / DDD–G / H–I 分段级放；每段至少3种体型，记录前侧投影、乳间分离、溢出、空杯与动态稳定。"],
    ["材料", "热湿环境穿着；遮点可见度；侧比伸长回复；肩带压强；钢圈通道磨耗。"],
    ["洗护", "至少10次机洗/晾干循环，观察钢圈外露、面料松弛、罩杯变形、肩带与扣眼耐久。"],
    ["宣称", "“减少1–1.5杯”“凉感”“不滑/不勒”等用语必须绑定内部或第三方测试标准，不在验证前用于Listing。"],
  ];
  validationRows.forEach((row, i) => {
    const r = 18 + i;
    spec.getRange(`A${r}`).values = [[row[0]]];
    spec.getRange(`B${r}:H${r}`).merge();
    spec.getRange(`B${r}`).values = [[row[1]]];
  });
  body(spec.getRange("A18:H21"));
  spec.getRange("A18:A21").format = { fill: COLORS.coralLight, font: { bold: true, color: COLORS.coral }, borders: { preset: "all", style: "thin", color: COLORS.grid }, verticalAlignment: "center" };
  spec.getRange("A18:H21").format.rowHeight = 54;
  addNote(spec, "A24:H27", "内容策略对应结构：真人报尺码→展示穿前/穿后侧面与正面→聚焦一个可见痛点（不滑、不溢、不勒、不形成uniboob、凉感）→展示穿T恤结果。FastMoss头部视频均有广告放大，创作时应先通过小预算或自然流量验证素材，再扩量。");
  setColumnWidths(spec, [["A", 17], ["B", 20], ["C", 20], ["D", 20], ["E", 20], ["F", 20], ["G", 20], ["H", 20]], 35);
  spec.freezePanes.freezeRows(2);

  const inspect = await wb.inspect({ kind: "region", sheetId: "Pain Matrix", range: "A1:N11", maxChars: 5000 });
  return { wb, inspect: inspect.ndjson ?? String(inspect) };
}

const samplesResult = await buildSamplesWorkbook();
const painResult = await buildPainWorkbook();

const verification = [];
verification.push(scanFormulaErrors(samplesResult.wb, "Amazon samples workbook"));
verification.push(scanFormulaErrors(painResult.wb, "Painpoint/design workbook"));
verification.push("Samples inspect:\n" + samplesResult.inspect.slice(0, 3500));
verification.push("Pain Matrix inspect:\n" + painResult.inspect.slice(0, 5000));

const samplePreviews = await renderAll(samplesResult.wb, "samples");
const painPreviews = await renderAll(painResult.wb, "pain");

const samplePath = path.join(outputDir, "amazon_minimizer_bra_samples_20260714.xlsx");
const painPath = path.join(outputDir, "minimizer_bra_painpoints_design_20260714.xlsx");
const sampleBlob = await SpreadsheetFile.exportXlsx(samplesResult.wb);
await sampleBlob.save(samplePath);
const painBlob = await SpreadsheetFile.exportXlsx(painResult.wb);
await painBlob.save(painPath);

await fs.copyFile(path.join(here, "minimizer_bra_design_concept.svg"), path.join(outputDir, "AirSculpt_Cool_Minimizer_design_concept.svg"));
await fs.copyFile(path.join(here, "minimizer_bra_design_concept.png"), path.join(outputDir, "AirSculpt_Cool_Minimizer_design_concept.png"));
await fs.writeFile(path.join(here, "verification_log.txt"), verification.join("\n\n"), "utf8");

console.log(JSON.stringify({
  samplePath,
  painPath,
  samplePreviews,
  painPreviews,
  verification: verification.slice(0, 2),
}, null, 2));
