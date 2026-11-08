const {chromium} = require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL,fileURLToPath}=require('url');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'test-output');
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url()))external.push(r.url());});
  let report=path.join(out,'scan-visible.html');
  const replay=process.argv.includes('--template-replay');
  if(replay){const previous=fs.readFileSync(report,'utf8'),match=previous.match(/<script id="scan-data" type="application\/json">([\s\S]*?)<\/script>/);assert(match,'Previous scan payload missing');report=path.join(out,'final-template-replay.html');fs.writeFileSync(report,fs.readFileSync(path.join(root,'src/report-template.html'),'utf8').replace('<!--DISK_DATA-->',()=>match[1]));}
  await page.goto(pathToFileURL(report).href);
  await page.waitForFunction(()=>document.getElementById('loading').hidden);
  assert.equal(await page.locator('#file-count').innerText(),'6');
  assert((await page.locator('#size-vrows .filename').first().innerText()).includes('large-sparse.bin'));
  await page.locator('#sort-size').click();
  assert.equal(await page.locator('#size-vrows .filename').first().innerText(),'zero');
  await page.locator('#sort-size').click();
  await page.getByRole('button',{name:'大小排序',exact:true}).click();
  assert.equal(await page.locator('body').getAttribute('data-mode'),'size');
  await page.locator('#size-vrows .row').filter({hasText:"中文&'记录.bin"}).getByRole('button',{name:'定位目录'}).click();
  assert.equal(await page.locator('body').getAttribute('data-mode'),'explorer');
  assert((await page.locator('#address').inputValue()).endsWith('资料'));
  assert((await page.locator('#folder-vrows .selected').innerText()).includes("中文&'记录.bin"));
  await page.locator('#up').click();
  await page.locator('#folder-vrows .row').filter({hasText:'empty'}).dblclick();
  assert((await page.locator('#folder-vrows').innerText()).includes('没有符合条件'));
  await page.locator('#back').click();await page.locator('#forward').click();
  assert((await page.locator('#address').inputValue()).endsWith('empty'));
  await page.getByRole('button',{name:'双栏',exact:true}).click();
  assert.equal(await page.locator('body').getAttribute('data-mode'),'split');
  await page.locator('#filter').fill('large-sparse');
  await page.waitForFunction(()=>document.getElementById('size-page').textContent.includes('/ 1'));
  assert.equal(await page.locator('#size-vrows .row').count(),1);
  await page.locator('#size-vrows .row').dblclick();
  assert(await page.locator('#file-dialog').isVisible());
  const fixture=JSON.parse(fs.readFileSync(path.join(out,'fixture-info.json'),'utf8'));
  assert.equal(fileURLToPath(await page.locator('#open-file').getAttribute('href')),path.join(fixture.root,'large-sparse.bin'));
  await page.locator('#dialog-close').click();await page.locator('#clear-filter').click();await page.locator('#up').click();
  await page.screenshot({path:path.join(out,'report-desktop.png'),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  // Test virtualization and pagination with a larger synthetic report. All
  // records must remain reachable, while only visible rows exist in the DOM.
  const template=fs.readFileSync(path.join(root,'src/report-template.html'),'utf8');
  const nodes=[[-1,'C:\\Synthetic',true,'0',null,null,16,'ok',0,true]];
  for(let i=0;i<12001;i++)nodes.push([0,'item-'+i+'.bin',false,String(i),null,null,0,'ok',0,true]);
  const payload={version:'synthetic-test',started:'2026-11-08T00:00:00Z',finished:'2026-11-08T00:00:01Z',seconds:1,hidden:false,cancelled:false,errors:0,skipped:0,hiddenSkipped:0,engines:['Synthetic test'],notes:[],nodes};
  const large=path.join(out,'synthetic-12001.html');fs.writeFileSync(large,template.replace('<!--DISK_DATA-->',()=>JSON.stringify(payload).replace(/</g,'\\u003c')));
  await page.goto(pathToFileURL(large).href);await page.waitForFunction(()=>document.getElementById('loading').hidden);
  assert((await page.locator('#size-vrows .row').count())<50);
  assert((await page.locator('#size-page').innerText()).includes('12,001'));
  await page.locator('#size-next').click();await page.locator('#size-next').click();
  assert((await page.locator('#size-page').innerText()).includes('10,001'));
  await page.locator('#size-vport').evaluate(el=>{el.scrollTop=el.scrollHeight;});
  await page.waitForTimeout(100);
  assert((await page.locator('#size-vrows .row').last().innerText()).includes('item-0.bin'));
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({status:'PASS',scope:replay?'final HTML template replay with earlier real scan data':'actual executable-generated report',template_sha256:require('crypto').createHash('sha256').update(template).digest('hex'),browser:await browser.version(),externalRequests:external.length,pageErrors:errors,checks:['size numeric order','mode switching','locate directory','folder navigation/back/forward','filter','file details/local URL','12001-record virtualization and full pagination']},null,2));
  console.log('Browser report checks: PASS');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
