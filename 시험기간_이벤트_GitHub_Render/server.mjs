import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {createHmac,timingSafeEqual,scryptSync,randomBytes} from 'node:crypto';
import pg from 'pg';
import {initialDatabase,validateDatabase,submitScores} from './domain.mjs';
const {DATABASE_URL,TEACHER_PASSWORD,SESSION_SECRET,NODE_ENV}=process.env;
if(!DATABASE_URL||!TEACHER_PASSWORD||!SESSION_SECRET||SESSION_SECRET.length<32)throw Error('DATABASE_URL, TEACHER_PASSWORD 및 32자 이상의 SESSION_SECRET을 설정해주세요.');
const pool=new pg.Pool({connectionString:DATABASE_URL,max:5,connectionTimeoutMillis:10000});
const html=await readFile(new URL('./public/index.html',import.meta.url));
await pool.query('CREATE TABLE IF NOT EXISTS exam_app (id INTEGER PRIMARY KEY, data JSONB NOT NULL, revision INTEGER NOT NULL DEFAULT 0, password_hash TEXT, recovery_question TEXT, recovery_answer_hash TEXT)');
await pool.query('INSERT INTO exam_app(id,data) VALUES(1,$1) ON CONFLICT(id) DO NOTHING',[JSON.stringify(initialDatabase())]);
const equal=(a,b)=>{const x=Buffer.from(a),y=Buffer.from(b);return x.length===y.length&&timingSafeEqual(x,y);};
const sign=x=>createHmac('sha256',SESSION_SECRET).update(x).digest('base64url');
const hash=p=>{const salt=randomBytes(16).toString('hex');return salt+':'+scryptSync(p,salt,64).toString('hex');};
const check=(p,h)=>{if(!h)return equal(p,TEACHER_PASSWORD);const [salt,digest]=h.split(':');return equal(scryptSync(p,salt,64).toString('hex'),digest);};
const authVersion=row=>sign(row.password_hash||TEACHER_PASSWORD);
function session(req,row){try{const token=(req.headers.cookie||'').split(';').map(x=>x.trim()).find(x=>x.startsWith('teacher_session='))?.slice(16);if(!token)return false;const [payload,sig]=token.split('.');if(!sig||!equal(sign(payload),sig))return false;const v=JSON.parse(Buffer.from(payload,'base64url'));return v.expires>Date.now()&&v.version===authVersion(row);}catch{return false;}}
function cookie(row,clear=false){const p=Buffer.from(JSON.stringify({expires:Date.now()+8*3600000,version:authVersion(row)})).toString('base64url');return 'teacher_session='+(clear?'':p+'.'+sign(p))+'; HttpOnly; SameSite=Strict; Path=/; Max-Age='+(clear?0:28800)+(NODE_ENV==='production'?'; Secure':'');}
async function body(req){let text='';for await(const chunk of req){text+=chunk;if(Buffer.byteLength(text)>20000000)throw Object.assign(Error('파일이 너무 큽니다.'),{status:413});}try{return JSON.parse(text);}catch{throw Object.assign(Error('요청 형식을 확인해주세요.'),{status:400});}}
const attempts=new Map();
function rate(req){const key=req.socket.remoteAddress;const now=Date.now();if(attempts.size>10000)attempts.clear();let item=attempts.get(key);if(!item||now>item.until){item={n:0,until:now+60000};attempts.set(key,item);}if(++item.n>30)throw Object.assign(Error('잠시 후 다시 시도해주세요.'),{status:429});}
function send(res,status,data,headers={}){res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff',...headers});res.end(JSON.stringify(data));}
const server=http.createServer(async(req,res)=>{
  try{
    const path=new URL(req.url,'http://localhost').pathname;
    if(req.method==='GET'&&path==='/healthz'){await pool.query('SELECT 1');return send(res,200,{ok:true});}
    if(req.method==='GET'&&path==='/'){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer'});return res.end(html);}
    if(!path.startsWith('/api/'))return send(res,404,{error:'찾을 수 없습니다.'});
    if(req.method==='POST'){
      const origin=req.headers.origin;const expected=(NODE_ENV==='production'?'https':'http')+'://'+req.headers.host;
      if(origin!==expected||!req.headers['content-type']?.startsWith('application/json'))return send(res,403,{error:'같은 사이트에서 다시 요청해주세요.'});
    }
    const row=(await pool.query('SELECT * FROM exam_app WHERE id=1')).rows[0];
    if(req.method==='GET'&&path==='/api/state')return send(res,200,{database:row.data,revision:row.revision,teacher:session(req,row)});
    if(req.method!=='POST')return send(res,405,{error:'지원하지 않는 요청입니다.'});
    const p=await body(req);
    if(path==='/api/login'){rate(req);if(typeof p.password!=='string'||p.password.length>256||!check(p.password,row.password_hash))return send(res,401,{error:'비밀번호가 맞지 않습니다.'});return send(res,200,{ok:true},{'Set-Cookie':cookie(row)});}
    if(path==='/api/logout')return send(res,200,{ok:true},{'Set-Cookie':cookie(row,true)});
    if(path==='/api/password'){
      if(!session(req,row))return send(res,401,{error:'교사 로그인이 필요합니다.'});
      if(typeof p.password!=='string'||!p.password.trim()||p.password.length>256)return send(res,400,{error:'비밀번호를 확인해주세요.'});
      const h=hash(p.password);await pool.query('UPDATE exam_app SET password_hash=$1,recovery_question=$2,recovery_answer_hash=$3 WHERE id=1',[h,String(p.question||'').slice(0,500),p.answer?hash(String(p.answer).slice(0,500)):null]);return send(res,200,{ok:true},{'Set-Cookie':cookie({...row,password_hash:h})});
    }
    if(path==='/api/state'){
      if(!session(req,row))return send(res,401,{error:'교사 로그인이 필요합니다.'});
      validateDatabase(p.database);
      const updated=await pool.query('UPDATE exam_app SET data=$1,revision=revision+1 WHERE id=1 AND revision=$2 RETURNING revision',[JSON.stringify(p.database),p.revision]);
      if(!updated.rowCount)return send(res,409,{error:'다른 기기에서 기록이 변경되었습니다. 현재 내용을 백업한 뒤 새로고침하여 다시 적용해주세요.'});
      return send(res,200,{revision:updated.rows[0].revision});
    }
    if(path==='/api/scores'){
      const client=await pool.connect();try{await client.query('BEGIN');const current=(await client.query('SELECT data,revision FROM exam_app WHERE id=1 FOR UPDATE')).rows[0];const data=submitScores(current.data,p);await client.query('UPDATE exam_app SET data=$1,revision=revision+1 WHERE id=1',[JSON.stringify(data)]);await client.query('COMMIT');return send(res,200,{database:data,revision:current.revision+1});}catch(e){await client.query('ROLLBACK');throw e;}finally{client.release();}
    }
    return send(res,404,{error:'찾을 수 없습니다.'});
  }catch(e){if(!e.status)console.error('Request failed:',e.message);send(res,e.status||503,{error:e.status?e.message:'서버에 연결하지 못했습니다. 입력 내용을 유지한 채 잠시 후 다시 시도해주세요.'});}
});
server.listen(Number(process.env.PORT)||3000,'0.0.0.0',()=>console.log('Exam events server ready'));
process.on('SIGTERM',()=>server.close(()=>pool.end()));
