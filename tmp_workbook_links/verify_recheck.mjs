import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const path='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07_复核版.xlsx';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path));
for(const n of ['日常TOP10','抹胸TOP10','前扣TOP10','束背TOP10','矫正TOP10','聚拢TOP10']){
 const s=wb.worksheets.getItem(n); const v=s.getUsedRange().values; const rows=v.slice(1).filter(r=>r[6]); const ranks=rows.map(r=>Number(r[4])); console.log(JSON.stringify({sheet:n,rows:rows.length,sorted:ranks.every((x,i)=>i===0||x>=ranks[i-1]),sports:rows.filter(r=>String(r[19]||'').includes('运动')).map(r=>[r[4],r[6],r[19]]),back:rows.filter(r=>String(r[19]||'').includes('束背')).map(r=>[r[4],r[6],r[19]])}));
}
console.log((await wb.inspect({kind:'region',sheetId:'复核记录',range:'A1:F12',maxChars:12000})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A',options:{useRegex:true,maxResults:100},summary:'verify'})).ndjson);
