import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load('C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx'));
const sh=wb.worksheets.getItem('日常TOP10');
try { console.log('deletefn',typeof sh.delete); sh.delete(); console.log('called'); } catch(e){ console.log('ERR',e.message); }
console.log((await wb.inspect({kind:'sheet',include:'id,name',maxChars:3000})).ndjson);
