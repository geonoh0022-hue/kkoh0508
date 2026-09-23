export function initialDatabase() {
  const year=String(new Date().getFullYear());
  return {version:3,activeYear:year,activeExam:'2-1',years:{[year]:{roster:[],sessions:{'2-1':{students:[],exams:[],lottoPredWindow:{start:'',end:''}}}}}};
}
export function validateDatabase(d){
  const fail=()=>{throw Object.assign(Error('기록 형식이 올바르지 않습니다.'),{status:400});};
  if(!d||d.version!==3||!d.years||Array.isArray(d.years)||Object.keys(d.years).length>201)fail();
  for(const [year,b] of Object.entries(d.years)){
    if(!/^(20\d{2}|21\d{2}|2200)$/.test(year)||!Array.isArray(b.roster)||b.roster.length>1000||!b.sessions)fail();
    const ids=new Set();for(const r of b.roster){if(!r||typeof r.id!=='string'||!/^[a-zA-Z0-9_-]{1,100}$/.test(r.id)||ids.has(r.id)||typeof r.name!=='string'||!r.name.trim()||r.name.length>100)fail();ids.add(r.id);}
    for(const [exam,s] of Object.entries(b.sessions)){
      if(!['1-1','1-2','2-1','2-2'].includes(exam)||!Array.isArray(s.students)||s.students.length!==ids.size||new Set(s.students.map(x=>x.id)).size!==ids.size||!Array.isArray(s.exams)||s.exams.length>500)fail();
      for(const x of s.students){if(!ids.has(x.id)||x.name!==b.roster.find(r=>r.id===x.id).name||!x.lotto)fail();for(const pair of Object.values(x.lotto)){for(const f of ['pred','actual']){const v=pair[f];if(v!==''&&(typeof v!=='string'&&typeof v!=='number'||!Number.isFinite(Number(v))||Number(v)<0||Number(v)>100))fail();}}}
      for(const x of s.exams){if(typeof x.subject!=='string'||!x.subject.trim()||x.subject.length>40||typeof x.subjectKey!=='string'||!/^(eng|math|sci|hist|sub_[a-f0-9_]+)$/.test(x.subjectKey))fail();}
      for(const field of ['lottoPredWindow','eventPeriod'])if(s[field])for(const key of ['start','end']){const v=s[field][key];if(typeof v!=='string'||v!==''&&!/^\d{4}-\d{2}-\d{2}$/.test(v))fail();}
    }
  }
  if(!d.years[d.activeYear]?.sessions[d.activeExam])fail();return d;
}
export function submitScores(d,p,today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())){
  const reject=(message,status=400)=>{throw Object.assign(Error(message),{status});};
  if(p.year!==d.activeYear||p.exam!==d.activeExam)reject('현재 시험이 변경되었습니다. 새로고침 후 다시 제출해주세요.',409);
  const s=d.years[d.activeYear].sessions[d.activeExam];const student=s.students.find(x=>x.id===p.studentId);
  if(!student||!['pred','actual'].includes(p.field))reject('학생 또는 점수 구분을 확인해주세요.');
  const w=s.lottoPredWindow||{};if(p.field==='pred'&&(w.start&&today<w.start||w.end&&today>w.end))reject('지금은 예상 점수 입력 기간이 아닙니다.',403);
  const keys=[...new Set(s.exams.filter(x=>x.subject.replace(/\s/g,'')!=='자기주도학습').map(x=>x.subjectKey))];
  if(!keys.length||!p.values||Object.keys(p.values).length!==keys.length)reject('등록된 모든 과목의 점수를 입력해주세요.');
  for(const k of keys){const v=p.values[k];if(v===''||!['number','string'].includes(typeof v)||!Number.isFinite(Number(v))||Number(v)<(p.field==='pred'?40:0)||Number(v)>100)reject('점수 범위를 확인해주세요.');}
  // Only change the submitted student's requested score field. Other concurrent records survive.
  for(const k of keys){student.lotto[k]??={pred:'',actual:''};student.lotto[k][p.field]=String(Number(p.values[k]));}return d;
}
