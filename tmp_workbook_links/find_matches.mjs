import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const inputPath = 'C:/Users/HSIA/Downloads/抖音大盘2026年上半年销量前100商品（文胸、运动内衣、贴合内衣、光腿神器）.xlsx';
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const needles = ['粉底液内衣','液体软支撑内衣','提拉修容内衣','水滴杯','幸棉'];
for (const name of ['文胸','运动内衣','贴合内衣','光腿神器']) {
  const sh = wb.worksheets.getItem(name);
  const vals = sh.getUsedRange().values;
  for (let r=0;r<vals.length;r++) {
    const row = vals[r].map(v=>v==null?'':String(v));
    const joined = row.join(' | ');
    if (needles.some(n=>joined.includes(n))) console.log(JSON.stringify({sheet:name,row:r+1,values:row.slice(0,8)}));
  }
}
