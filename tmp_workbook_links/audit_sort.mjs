import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load('C:/Users/HSIA/Desktop/任务/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx'));
for (const s of wb.worksheets.items.slice(1)) {
 const v=s.getUsedRange().values.slice(1).filter(r=>r[4]!=null&&r[6]);
 const ranks=v.map(r=>Number(r[4]));
 console.log(JSON.stringify({sheet:s.name,count:ranks.length,sorted:ranks.every((x,i)=>i===0||x>=ranks[i-1]),unique:new Set(ranks).size===ranks.length,min:ranks[0],max:ranks.at(-1)}));
}
