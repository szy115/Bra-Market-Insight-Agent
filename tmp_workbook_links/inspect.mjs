import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const inputPath = 'C:/Users/HSIA/Downloads/抖音大盘2026年上半年销量前100商品（文胸、运动内衣、贴合内衣、光腿神器）.xlsx';
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const summary = await workbook.inspect({ kind: 'workbook,sheet,table', maxChars: 10000, tableMaxRows: 5, tableMaxCols: 12, tableMaxCellChars: 100 });
console.log(summary.ndjson);
for (const name of ['文胸','运动内衣','贴合内衣','光腿神器']) {
  const sheet = workbook.worksheets.getItem(name);
  const used = sheet.getUsedRange();
  console.log(`---${name} used=${used.address ?? ''}---`);
  const region = await workbook.inspect({ kind: 'region', sheetId: name, range: 'A1:J8', maxChars: 6000 });
  console.log(region.ndjson);
}
