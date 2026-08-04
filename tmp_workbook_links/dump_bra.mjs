import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const p='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(p));
const names=['日常TOP10','抹胸TOP10','前扣TOP10','束背TOP10','矫正TOP10','聚拢TOP10'];
for(const n of names){const v=wb.worksheets.getItem(n).getUsedRange().values; console.log('\n###'+n); for(let i=1;i<v.length;i++){if(v[i][6]) console.log(JSON.stringify({row:i+1,rank:v[i][4],title:v[i][6],id:v[i][7],url:v[i][10],price:v[i][11],evidence:v[i][18],tags:v[i][19],floor:v[i][20],summary:v[i][21]}));}}
