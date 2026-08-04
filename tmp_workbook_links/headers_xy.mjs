import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load('C:/Users/HSIA/Desktop/任务/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx'));
for(const n of ['日常TOP10','束背TOP10']){const s=wb.worksheets.getItem(n);console.log(n,JSON.stringify(s.getRange('A1:X2').values));}
