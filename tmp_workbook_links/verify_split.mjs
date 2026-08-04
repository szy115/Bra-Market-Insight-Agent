import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const p='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1/文胸商品_分类TOP10_按主卖点_胸型双榜_2026-07.xlsx';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(p));
console.log((await wb.inspect({kind:'sheet',include:'id,name',maxChars:12000})).ndjson);
for(const n of ['日常（大胸）TOP10','日常（小胸）TOP10','抹胸（大胸）TOP10','抹胸（小胸）TOP10','前扣（大胸）TOP10','前扣（小胸）TOP10','束背（大胸）TOP10','束背（小胸）TOP10','矫正（大胸）TOP10','矫正（小胸）TOP10','聚拢（大胸）TOP10','聚拢（小胸）TOP10']){
 const sh=wb.worksheets.getItem(n); const u=sh.getUsedRange(); const v=u.values; const f=sh.getRange(`K1:K${Math.min(4,v.length)}`).formulas; const ids=[]; for(let i=1;i<v.length;i++) if(v[i][7]) ids.push(String(v[i][7])); console.log(n,'rows',ids.length,'ranks',ids.map((_,i)=>v[i+1][4]),'Kformulas',JSON.stringify(f),'unique',new Set(ids).size===ids.length);
}
for(const n of ['女士内裤TOP10','塑身衣TOP10']){const sh=wb.worksheets.getItem(n); console.log(n,JSON.stringify(sh.getRange('K1:S3').formulas));}
const raw=wb.worksheets.getItemAt(0); console.log('RAW',JSON.stringify(raw.getRange('K1:S3').formulas));
console.log('ERR', (await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A',options:{useRegex:true,maxResults:300},summary:'verify'})).ndjson);
