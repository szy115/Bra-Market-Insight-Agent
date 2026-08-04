import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const p='C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1/文胸商品_分类TOP10_按主卖点_胸型双榜_全量复核版_2026-07.xlsx';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(p));
for(const n of ['日常（大胸）TOP10','日常（小胸）TOP10','聚拢（大胸）TOP10','聚拢（小胸）TOP10','抹胸（大胸）TOP10','前扣（大胸）TOP10','运动（大胸）TOP10','全量判定']){const v=wb.worksheets.getItem(n).getUsedRange().values;console.log(n,v.length-1,'first',v[1]?.[6]||v[1]?.[1]||'');}
console.log('LINK',JSON.stringify(wb.worksheets.getItem('日常（大胸）TOP10').getRange('K2:K3').formulas));
console.log('BASIS',JSON.stringify(wb.worksheets.getItem('日常（大胸）TOP10').getRange('Y1:AB3').values));
console.log('ERRORS',(await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A',options:{useRegex:true,maxResults:300},summary:'verify exported'})).ndjson);
