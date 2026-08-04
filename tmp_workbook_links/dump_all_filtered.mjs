import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const p='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1/文胸商品_分类TOP10_按主卖点_胸型双榜_2026-07.xlsx';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(p));
const sh=wb.worksheets.getItemAt(0); const v=sh.getUsedRange().values;
function floor(p){const nums=String(p??'').match(/\d+(?:\.\d+)?/g); return nums?.length?Math.min(...nums.map(Number)):null;}
const out=[]; for(let i=1;i<v.length;i++){const f=floor(v[i][11]); if(f!=null&&f>=120) out.push({row:i+1,rank:v[i][4],title:v[i][6],id:String(v[i][7]),price:v[i][11],floor:f,url:v[i][18]||v[i][10]});}
console.log('COUNT',out.length); for(const x of out) console.log(JSON.stringify(x));
