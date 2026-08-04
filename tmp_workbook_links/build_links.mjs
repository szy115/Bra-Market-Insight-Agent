import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const inputPath = 'C:/Users/HSIA/Downloads/抖音大盘2026年上半年销量前100商品（文胸、运动内衣、贴合内衣、光腿神器）.xlsx';
const outputDir = 'C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1';
const outputPath = `${outputDir}/抖音大盘2026年上半年销量前100商品_已提取链接.xlsx`;
await fs.mkdir(outputDir, { recursive: true });

const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheet = wb.worksheets.getItem('贴合内衣');
const rowCount = 58;

// Extend the existing sheet with traceable extraction fields while preserving the source columns.
const extraCols = ['E','F','G','H','I','J','K'];
for (const col of extraCols) {
  sheet.getRange(`${col}1:${col}${rowCount}`).copyFrom(sheet.getRange(`D1:D${rowCount}`), 'all');
}
sheet.getRange('E1:K1').values = [[
  '好货链接', '商品ID', '已匹配商品名称', '参考售价', '店铺', '提取状态', '来源视频弹窗链接'
]];

const rows = Array.from({ length: rowCount - 1 }, () => [null, null, null, null, null, null]);
const setRow = (excelRow, values) => {
  rows[excelRow - 2] = values;
};
const searchUrl = (query, modalId) => `https://www.douyin.com/search/${encodeURIComponent(query)}?modal_id=${modalId}`;
setRow(2, [null, '嫦香诗原创法式蕾丝内衣女小胸聚拢显大收副乳防下垂性感文胸套装', '79.9起', '嫦香诗官方旗舰店', '已定位购物卡；商品ID待提取', searchUrl('豆沙色蕾丝贴合内衣', '7655609874151808692')]);
setRow(3, [null, '【赵露思同款】幸棉粉底液内衣隐形无痕舒适百搭文胸女*d', '125.1起', '幸棉Luckmeey内衣旗舰店', '关键词相近；商品ID待提取', searchUrl('幸棉小纱窗无痕果冻无感贴合内衣薄款显瘦显小隐形无痕文胸zb', '7546791255872326971')]);
setRow(5, [null, '【明星同款】幸棉液体软支撑内衣无钢圈舒适自然挺拔文胸罩文胸*d', '125', '幸棉Luckmeey内衣旗舰店', '关键词相近（水滴杯）；商品ID待提取', searchUrl('幸棉内衣小水滴', '7600072443784595803')]);
setRow(6, [null, '【粉丝专享】幸棉提拉修容内衣大胸显小防下垂收副乳软支撑聚拢*d', '169起', '幸棉Luckmeey官方旗舰店', '关键词相近；商品ID待提取', searchUrl('幸棉大胸显小全罩杯纱窗软支撑无痕果冻无感贴合内衣zb', '7654500611727266745')]);
setRow(4, [null, null, null, null, '暂未匹配到对应购物卡', null]);
sheet.getRange(`F2:K${rowCount}`).values = rows;
const linkFormulas = Array.from({ length: rowCount - 1 }, (_, i) => {
  const r = i + 2;
  return [`=IF(F${r}<>"","https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id="&F${r}&"&origin_type=pc_compass_manage","")`];
});
sheet.getRange(`E2:E${rowCount}`).formulas = linkFormulas;

// Keep the existing body style and make the added fields readable.
sheet.getRange('E1:K1').format = { font: { bold: true, fontSize: 12, color: '#000000' } };
sheet.getRange(`E2:K${rowCount}`).format = { font: { fontSize: 12, color: '#000000' }, wrapText: true };
sheet.getRange(`E1:E${rowCount}`).format.columnWidth = 42;
sheet.getRange(`F1:F${rowCount}`).format.columnWidth = 22;
sheet.getRange(`G1:G${rowCount}`).format.columnWidth = 42;
sheet.getRange(`H1:H${rowCount}`).format.columnWidth = 12;
sheet.getRange(`I1:I${rowCount}`).format.columnWidth = 24;
sheet.getRange(`J1:J${rowCount}`).format.columnWidth = 28;
sheet.getRange(`K1:K${rowCount}`).format.columnWidth = 42;
sheet.getRange('E1:K1').format.rowHeight = 24;
sheet.getRange('E2:K6').format.rowHeight = 42;

const check = await wb.inspect({ kind: 'table', sheetId: '贴合内衣', range: 'A1:K8', include: 'values,formulas', tableMaxRows: 8, tableMaxCols: 11, maxChars: 12000 });
console.log(check.ndjson);
const errors = await wb.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A', options: { useRegex: true, maxResults: 100 }, summary: 'final formula error scan' });
console.log(errors.ndjson);
const preview = await wb.render({ sheetName: '贴合内衣', range: 'A1:K8', scale: 1, format: 'png' });
await fs.writeFile(`${outputDir}/贴合内衣_链接预览.png`, new Uint8Array(await preview.arrayBuffer()));
const out = await SpreadsheetFile.exportXlsx(wb);
await out.save(outputPath);
console.log(`OUTPUT=${outputPath}`);

