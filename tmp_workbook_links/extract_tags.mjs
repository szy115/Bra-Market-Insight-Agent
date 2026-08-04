import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const path='C:/Users/HSIA/Desktop/任务/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path));
for (const name of ['日常TOP10','抹胸TOP10','前扣TOP10','束背TOP10','矫正TOP10','聚拢TOP10','女士内裤TOP10','塑身衣TOP10']) {
  const v=wb.worksheets.getItem(name).getUsedRange().values;
  console.log(`###${name}`);
  for(let r=1;r<v.length;r++){
    const a=v[r];
    console.log(JSON.stringify({row:r+1,rank:a[4],product:a[6],price:a[11],evidence:a[18],tags:a[19],minPrice:a[20],summary:a[21],status:a[22],link:a[10]}));
  }
}
