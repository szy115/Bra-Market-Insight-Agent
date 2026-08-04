import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load('C:/Users/HSIA/Desktop/任务/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx'));
for(const s of wb.worksheets.items){console.log(JSON.stringify({sheet:s.name,tables:s.tables.items.map(t=>({name:t.name,style:t.style,address:t.getRange?.().address}))}));}
