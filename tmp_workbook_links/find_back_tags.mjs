import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load('C:/Users/HSIA/Desktop/任务/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx'));
for(const s of wb.worksheets.items){const v=s.getUsedRange().values;for(let r=1;r<v.length;r++){const tags=String(v[r][19]??'');if(tags.includes('束背'))console.log(JSON.stringify({sheet:s.name,row:r+1,rank:v[r][4],product:v[r][6],tags,evidence:v[r][18],summary:v[r][21]}));}}
