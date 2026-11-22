const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../public/js/dvj-analytics.js'), 'utf8');

function setup({url = 'https://sigma-awards.data-visualization.jp/?q=private%40example.com&year=2026&utm_source=news#anchor', enabled = true, malformed = false} = {}) {
  const scripts = [], handlers = {};
  const config = {enabled,measurement_id:'G-0DP20HK462',site_id:'sigma_awards',production_hosts:['sigma-awards.data-visualization.jp']};
  const location = new URL(url);
  const document = {
    title:'Catalog',referrer:'https://data-visualization.jp/?q=secret#anchor',
    getElementById: () => ({textContent: malformed ? '{' : JSON.stringify(config)}),
    addEventListener: (name, handler) => { handlers[name] = handler; },
    createElement: () => ({}),head:{appendChild: script => scripts.push(script)},
  };
  const window = {};
  const context = vm.createContext({window,document,location,URL,Date,Set,Number,Object,encodeURIComponent});
  vm.runInContext(source,context);
  const calls = () => (window.dataLayer || []).map(args => Array.from(args));
  const events = name => calls().filter(c => c[0] === 'event' && (!name || c[1] === name));
  return {window,document,location,scripts,context,calls,events,handlers};
}

test('initial view is automatic once, with sanitized location and referrer', () => {
  const x=setup();
  const config=x.calls().find(c=>c[0]==='config')[2];
  assert.equal(config.send_page_view,true);
  assert.equal(config.page_location,'https://sigma-awards.data-visualization.jp/?utm_source=news');
  assert.equal(config.page_referrer,'https://data-visualization.jp/');
  assert.equal(x.events('page_view').length,0);
  assert.equal(x.scripts.length,1);
});
test('localhost, preview, lookalike domain and HTTP send nothing', () => {
  for(const url of ['http://localhost:1313/','https://deploy-preview-1.netlify.app/','https://sigma-awards.data-visualization.jp.example.com/','http://sigma-awards.data-visualization.jp/']) {
    const x=setup({url});assert.equal(x.calls().length,0);assert.equal(x.scripts.length,0);
  }
});
test('disabled or malformed settings do not load Google', () => {
  for(const options of [{enabled:false},{malformed:true}]) assert.equal(setup(options).scripts.length,0);
});
test('loading the runtime twice does not double-initialize', () => {
  const x=setup();vm.runInContext(source,x.context);
  assert.equal(x.scripts.length,1);assert.equal(x.calls().filter(c=>c[0]==='config').length,1);
});
test('filters and pagination stay events and do not become views', () => {
  const x=setup();
  x.window.dvjAnalytics.pageView('https://sigma-awards.data-visualization.jp/?q=secret&page=2','Catalog');
  x.window.dvjAnalytics.event('filter_apply',{has_search:true,result_count:10,query:'secret',country:'private'});
  x.window.dvjAnalytics.event('pagination_change',{page:2});
  assert.equal(x.events('page_view').length,0);
  assert.equal(x.events('filter_apply').length,1);
  assert.equal(x.events('pagination_change').length,1);
  assert.equal(JSON.stringify(x.calls()).includes('secret'),false);
});
test('detail, another detail, Back to detail and list each produce one view', () => {
  const x=setup();
  const base='https://sigma-awards.data-visualization.jp';
  for(const [url,title] of [['/entries/a/','A'],['/entries/a/?q=secret','A'],['/entries/b/','B'],['/entries/a/','A'],['/?q=secret','Catalog']]) x.window.dvjAnalytics.pageView(base+url,title);
  const views=x.events('page_view');assert.equal(views.length,4);
  assert.equal(views[1][2].page_referrer,base+'/entries/a/');
  assert.equal(views[3][2].page_title,'Catalog');
  assert.equal(x.calls().filter(c=>c[0]==='config'&&c[2].send_page_view===false).length,4);
});
test('virtual views cannot target a different site', () => {
  const x=setup();x.window.dvjAnalytics.pageView('https://other.example/entries/a/','Other');
  assert.equal(x.events().length,0);
});
test('community and registration links have distinct purposes and no raw URL', () => {
  const x=setup();
  for(const href of ['https://data-visualization-japan.connpass.com/','https://data-visualization-japan.connpass.com/event/123/?q=secret']) x.handlers.click({target:{closest:()=>({href})}});
  assert.equal(x.events('community_click').length,1);
  assert.equal(x.events('registration_click').length,1);
  assert.equal(JSON.stringify(x.events()).includes('secret'),false);
});
test('invalid events and arbitrary fields are rejected', () => {
  const x=setup();x.window.dvjAnalytics.event('arbitrary',{email:'private@example.com'});
  x.window.dvjAnalytics.event('video_load',{video_id:'https://bad'});
  x.window.dvjAnalytics.event('language_change',{language:'src'});
  assert.equal(x.events('arbitrary').length,0);
  assert.equal(Object.keys(x.events('video_load')[0][2]).length,0);
  assert.equal(x.events('language_change')[0][2].language,'src');
});

test('Sigma actual navigation hooks count detail open, Back, Forward and close once', async () => {
  const x=setup({url:'https://sigma-awards.data-visualization.jp/'});
  const location=x.location;
  const noop=()=>{};
  const element=()=>({dataset:{},hidden:true,value:'',textContent:'',focus:noop,contains:()=>false,querySelectorAll:()=>[],setAttribute:noop});
  const elements=new Map();
  x.document.body={dataset:{},style:{}};
  x.document.activeElement=x.document.body;
  x.document.querySelector=selector=>{if(!elements.has(selector))elements.set(selector,element());return elements.get(selector)};
  const stack=[{url:location.href,state:null}];let position=0;
  const history={
    state:null,
    pushState(state,_,url){this.state=state;location.href=new URL(url,location.href).href;stack.splice(++position);stack.push({url:location.href,state})},
    replaceState(state,_,url){this.state=state;location.href=new URL(url,location.href).href;stack[position]={url:location.href,state}},
    back(){if(position>0){const next=stack[--position];location.href=next.url;this.state=next.state;}},
    forward(){if(position<stack.length-1){const next=stack[++position];location.href=next.url;this.state=next.state;}},
  };
  Object.assign(x.context,{history,URLSearchParams,console});
  const pending=[];
  Object.assign(x.window,{clearTimeout:()=>pending.splice(0),setTimeout:fn=>{pending.push(fn);return pending.length}});
  let app=fs.readFileSync(path.join(__dirname,'../public/js/app.js'),'utf8');
  app=app.replace(/^import[^\n]+\n/,'').replace(/\ninit\(\);\s*$/,'');
  vm.runInContext(app+`\n
    renderDrawer = () => {};
    displayTitle = entry => entry.title;
    loadDetails = async () => ({});
    readUrl = normalizeYear = applyUrlToForm = renderYearChips = renderLocaleChips = renderCategories = renderCountries = applyFilters = renderCards = () => {};
    state.entries = [{id:'2026-s-0001',year:2026,title:'First'},{id:'2026-s-0002',year:2026,title:'Second'}];
    state.filtered = state.entries;
    window.appTest = {openDrawer,closeDrawer,syncFromPopState,writeUrl,requestCloseDrawer,setQuery: value => {state.query=value}};
  `,x.context);
  const appTest=x.window.appTest;
  await appTest.openDrawer('2026-s-0001',null,{mode:'push'});
  assert.equal(x.events('page_view').length,1);
  history.back();appTest.syncFromPopState();
  assert.equal(x.events('page_view').length,2);
  history.forward();appTest.syncFromPopState();
  assert.equal(x.events('page_view').length,3);
  appTest.requestCloseDrawer();appTest.syncFromPopState();
  assert.equal(x.events('page_view').length,4);
  appTest.setQuery('secret@example.com');appTest.writeUrl({replace:true});while(pending.length)pending.shift()();
  assert.equal(x.events('page_view').length,4);
  assert.equal(x.events('filter_apply').length,1);
  assert.equal(JSON.stringify(x.calls()).includes('secret@example.com'),false);
  assert.equal(x.events('page_view')[0][2].page_title,'First | Sigma Awards 2026');
});
