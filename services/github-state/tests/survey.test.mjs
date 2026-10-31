import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {build} from 'esbuild';
import {runtime,repository,response,send} from './runtime.mjs';

const bundle=await build({entryPoints:['src/survey.ts'],bundle:true,platform:'node',format:'esm',write:false});
const facts=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
test('Mei recovery uses the same exact-head handoff contract as Tau Ceti',()=>{
 const head='e53dccb6abd43a803fb90a84e8b4aee50fc16f7e';
 const comment=(login,sha=head)=>({id:'1',user:{login},body:'Merge-queue recovery for head `e53dccb`: integration repair\n\n<!--tauceti-rebase:v1 '+sha+'-->'});
 for(const login of ['mei-automation[bot]','tauceti-review-bot[bot]','tau-ceti-bors[bot]'])
  assert.deepEqual(facts.summarize([comment(login)],[]).rebase_heads,[head]);
 for(const login of ['mei-automation','untrusted[bot]','author','MEI-AUTOMATION[bot]'])
  assert.deepEqual(facts.summarize([comment(login)],[]).rebase_heads,[]);
 for(const sha of ['e53dccb',head.toUpperCase(),'g'.repeat(40)])
  assert.deepEqual(facts.summarize([comment('mei-automation[bot]',sha)],[]).rebase_heads,[]);
 const quoted=comment('mei-automation[bot]');quoted.body='Quoted\n'+quoted.body;
 assert.deepEqual(facts.summarize([quoted],[]).rebase_heads,[]);
});
test('Python fallback and TypeScript projection agree on 240 changing histories and scopes',()=>{
 const process=spawnSync('python3',['../../tests/fixtures/survey_facts_parity.py'],{encoding:'utf8',maxBuffer:5000000});
 assert.equal(process.status,0,process.stderr);
 for(const c of JSON.parse(process.stdout)) {
  assert.deepEqual(facts.summarize(c.issues,c.reviews),c.expected);
  assert.deepEqual(facts.targetFocuses(c.row.body),c.focuses);
  assert.equal(facts.inScope(c.row,c.scope,c.skip),c.included);
 }
});

test('compact survey is authenticated, roadmap scoped and does not issue GitHub requests',async()=>{
 let network=0;
 const mf=await runtime(async()=>{network++;return response([],'core');},{},{repositoryAlarms:false});
 try {
  const ns=await mf.getDurableObjectNamespace('REPOSITORIES'),stub=ns.get(ns.idFromName('100'));
  // Seed repository identity without scheduling the unrelated bootstrap.
  // Configure deliberately starts background GitHub work, which can overlap
  // this assertion on a busy runner even though the survey itself is local.
  const key='webhooks/survey-fixture.json';
  await (await mf.getR2Bucket('ARCHIVE')).put(key,'{}');
  await send(stub,'/event',{key,delivery:'survey-fixture',event:'ping',repository:repository.name,received:Date.now()});
  const before=network;
  const r=await mf.dispatchFetch('https://test/v1/query?repository=org/repo&operation=survey&args='+encodeURIComponent(JSON.stringify({roadmap:'PDE',skip:'',numbers:''})),{headers:{Authorization:'Bearer client'}});
  assert.equal(r.status,200);const payload=await r.json();
  assert.equal(payload.contract,facts.SURVEY_CONTRACT);assert.equal(payload.status,'unavailable');assert.equal(network,before);
  assert.equal((await mf.dispatchFetch('https://test/v1/query?repository=org/repo&operation=survey',{headers:{Authorization:'Bearer invalid'}})).status,401);
 }finally{await mf.dispose();}
});

test('obsolete pause markers are not projected, including previously stored fragments',()=>{
 const head='a'.repeat(40), marker='<!--tauceti-blocked:v1 '+head+'-->';
 assert.equal('blocked' in facts.summarize([{body:marker+'\nEvidence',user:{login:'Author'}}],[]),false);
 assert.equal('blocked' in facts.summarizeFragments([{meta:null,rebase_heads:[],marker:null,blocked:[{head,author:'author'}]}],[]),false);
});


test('in-progress scoreboards cannot replace completed verdicts in compact or direct facts',()=>{
 const head='a'.repeat(40), previous='b'.repeat(40);
 const board=(id,updated,meta)=>({id,updated_at:updated,body:'<!--tauceti-scoreboard--> <!--tauceti-meta:v1 '+JSON.stringify(meta)+'-->'});
 const done=board('1','1',{head_sha:previous,states:{reuse:'green'},runs:[]});
 const init=board('2','2',{head_sha:head,mode:'init',states:{reuse:'blocking_request',scope:'stale'},runs:[]});
 assert.equal(facts.summarize([done,init],[]).meta.head_sha,previous);
 assert.equal(facts.summarize([init],[]).meta,null);
 assert.equal(facts.issueFragment(init).meta,null);
 assert.notEqual(facts.SURVEY_INDEX_VERSION,facts.SURVEY_CONTRACT);
});


test('old coordination comments and cached fragments do not project claims',()=>{
 const body='<!--tauceti-review-in-progress '+JSON.stringify({head:'a'.repeat(40),expires_at:9999999999,providers:['claude']})+'-->';
 assert.equal('markers' in facts.summarize([{body}],[]),false);
 assert.equal('markers' in facts.summarizeFragments([{meta:null,rebase_heads:[],marker:{head:'a'.repeat(40),expires_at:9999999999}}],[]),false);
});
