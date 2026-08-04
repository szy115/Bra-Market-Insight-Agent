import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const p='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(p));
console.log((await wb.inspect({kind:'sheet',include:'id,name',maxChars:6000})).ndjson);
console.log((await wb.inspect({kind:'workbook,sheet,table',maxChars:10000,tableMaxRows:3,tableMaxCols:12,tableMaxCellChars:120})).ndjson);
for (const n of ['日常TOP10','抹胸TOP10','前扣TOP10','束背TOP10','矫正TOP10','聚拢TOP10','女士内裤TOP10','塑身衣TOP10','复核记录']){
  try { const sh=wb.worksheets.getItem(n); const u=sh.getUsedRange(); console.log('\nSHEET',n,'rows',u.values.length,'cols',u.values[0]?.length); console.log((await wb.inspect({kind:'table',sheetId:n,range:`A1:X${Math.min(15,u.values.length)}`,include:'values,formulas',tableMaxRows:15,tableMaxCols:24,maxChars:16000})).ndjson); }
  catch(e){console.log('ERR',n,e.message)}
}
