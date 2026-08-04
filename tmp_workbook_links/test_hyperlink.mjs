import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load('C:/Users/HSIA/Documents/Insight Agent/outputs/019fb790-7bca-74d2-bfc0-13b4d3e965e1/文胸商品_分类TOP10_按原榜排名_含内裤塑身衣_2026-07.xlsx'));
const sh=wb.worksheets.getItem('日常TOP10');
sh.getRange('Y1').values=[['测试']]; sh.getRange('Y2').formulas=[['=HYPERLINK("https://example.com","打开")']];
console.log('v',JSON.stringify(sh.getRange('Y1:Y2').values)); console.log('f',JSON.stringify(sh.getRange('Y1:Y2').formulas)); console.log((await wb.inspect({kind:'formula',sheetId:'日常TOP10',range:'Y1:Y2',maxChars:2000})).ndjson);
