import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const path='C:/Users/HSIA/Desktop/任务/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path));
console.log((await wb.inspect({kind:'workbook,sheet,table',maxChars:12000,tableMaxRows:12,tableMaxCols:14,tableMaxCellChars:160})).ndjson);
for (const s of wb.worksheets.items) {
  const name=s.name;
  const used=s.getUsedRange();
  console.log(`---${name}---`);
  console.log((await wb.inspect({kind:'region',sheetId:name,range:'A1:N15',maxChars:12000})).ndjson);
}
