# 시험기간 이벤트 — GitHub + Render 배포용

원본의 디자인, 화면 구성, 이벤트 규칙, 시험 안내, 학년도·시험 구분을 유지한 서버 저장 버전입니다. GitHub 업로드와 Render 배포는 사용자가 진행합니다.

## 먼저 알아두기

- GitHub는 코드를 보관하고, Render Web Service는 프로그램을 실행하며, PostgreSQL은 학생 기록을 보관합니다.
- Render 무료 서버 안에 JSON/SQLite 파일을 저장하면 재시작·재배포 때 지워질 수 있습니다. 이 패키지는 별도 PostgreSQL에 저장합니다.
- Render 무료 PostgreSQL은 생성 후 30일 만료이므로 장기 기록용 기본 선택으로 삼지 않았습니다. 아래에서는 Neon의 무료 PostgreSQL을 연결합니다. 서비스별 무료 한도와 정책은 가입 화면에서 확인하세요.
- 원본 파일을 더블클릭해 사용하는 방식이 아닙니다. 배포 후 생성된 HTTPS 주소를 사용합니다.
- 데이터베이스 연결 주소와 교사 비밀번호를 실제로 설정해야 작동합니다. ZIP에는 실제 계정이나 비밀번호가 들어 있지 않습니다.

## 1. GitHub에 업로드

1. ZIP을 압축 해제합니다.
2. GitHub에서 새 저장소를 만듭니다. Private을 권장합니다. 공개 저장소여도 앱 소스에는 실제 학생 기록이 들어 있지 않습니다.
3. Add file → Upload files에서 압축을 푼 폴더 안의 파일과 폴더를 올립니다. ZIP 자체를 올리지 마세요.
4. 저장소 최상위에 package.json, pnpm-lock.yaml, server.mjs, render.yaml이 보이는지 확인합니다.
5. public 폴더, original 폴더, test 폴더도 함께 올립니다. .env.example은 예시 파일입니다. 실제 .env는 올리지 않습니다.

GitHub Pages로는 이 서버를 실행할 수 없습니다. 다음 단계에서 Render의 Web Service를 사용합니다.

## 2. 기록 저장용 데이터베이스 만들기

1. https://neon.com 에서 가입하고 Free 프로젝트를 만듭니다.
2. Connect에서 PostgreSQL 연결 문자열을 복사합니다. 보통 postgresql:// 로 시작합니다. 연결 풀링이 제공되면 활성화할 수 있습니다.
3. 주소 전체를 보관합니다. Render의 DATABASE_URL에 넣을 값이며 비밀번호가 포함된 비밀 정보입니다.
4. 이 앱이 사용할 전용 데이터베이스/프로젝트를 쓰세요. 앱은 최초 실행 시 exam_app 테이블을 자동 생성합니다. 샘플 학생이나 점수를 생성하지 않습니다.

이미 PostgreSQL이 있다면 그 연결 문자열을 사용해도 됩니다. TLS 옵션은 제공 업체의 안내를 따르세요. 인증서 검증을 끄는 코드는 포함하지 않았습니다.

## 3. Render에서 실행 — 쉬운 방법: Blueprint

1. https://dashboard.render.com 에 로그인하고 GitHub 저장소 접근을 연결합니다.
2. New → Blueprint에서 해당 저장소를 선택합니다.
3. 저장소의 render.yaml이 무료 Web Service 설정을 불러옵니다.
4. 아래 두 값을 입력합니다.

| 이름 | 넣을 값 |
| --- | --- |
| DATABASE_URL | 앞에서 복사한 PostgreSQL 연결 문자열 전체 |
| TEACHER_PASSWORD | 본인이 정한 교사 비밀번호. 길고 추측하기 어려운 값을 사용하세요. |

SESSION_SECRET은 Blueprint가 자동 생성합니다. NODE_ENV는 production으로 설정되어 있습니다. 유료 데이터베이스나 디스크를 자동 생성하지 않습니다.

5. 생성/배포를 시작하고 Live 상태가 될 때까지 기다립니다.
6. 표시된 onrender.com 주소로 접속합니다.

## 3-1. Web Service를 직접 만드는 경우

New → Web Service → GitHub 저장소 선택 후 아래처럼 설정합니다.

| 항목 | 값 |
| --- | --- |
| Runtime / Language | Node |
| Root Directory | 비워둠. 파일을 하위 폴더에 올렸다면 그 폴더 지정 |
| Build Command | pnpm install --frozen-lockfile |
| Start Command | pnpm start |
| Instance Type | Free |
| Health Check Path | /healthz |

환경 변수는 DATABASE_URL, TEACHER_PASSWORD, SESSION_SECRET, NODE_ENV가 필요합니다. SESSION_SECRET은 32자 이상의 임의 문자열, NODE_ENV는 production을 입력합니다. package.json은 Node 22.x를 지정합니다. PORT는 Render가 제공하므로 직접 설정할 필요가 없습니다.

## 4. 선생님 최초 설정과 학생 배포

1. 기본 주소에서 상단 교사 관리에 TEACHER_PASSWORD 값을 입력합니다.
2. 학년도와 시험을 고르고 학생 명단, 시험 과목, 입력 기간을 설정합니다.
3. 저장 상태에 ‘서버 저장됨’이 표시되는지 확인합니다.
4. 학생에게는 배포 주소 끝에 /?student=1 을 붙여 공유하면 바로 학생 화면이 열립니다.
5. 학생은 기존과 동일하게 이름을 선택하고 예상/실제 점수를 제출합니다. 제출 완료 안내는 서버가 저장한 뒤 표시됩니다.
6. 다른 기기에서 같은 주소로 접속해 저장 결과를 확인합니다. 입력 중이지 않은 화면은 주기적으로 갱신하며, 즉시 최신 기록이 필요하면 새로고침합니다.

기존 학생 화면은 ‘이름 선택’ 방식이며 학생별 계정 인증이 아닙니다. 이 방식을 유지했으므로 링크를 가진 사람은 다른 이름을 선택할 수도 있고 기록을 조회할 수 있습니다. 이 패키지는 학생별 성적 비공개 시스템이 아닙니다. 학급에서 공유할 수 있는 범위로 사용하고, 학생 본인 인증이 필요하면 별도 기능이 필요합니다.

## 기존 기록 옮기기

HTML 파일 자체에는 기존 브라우저에 입력해 둔 기록이 포함되지 않습니다.

1. 기존 파일을 기록이 저장된 브라우저에서 엽니다.
2. 기존 교사 비밀번호로 로그인 → 기록 백업 → JSON 파일 저장.
3. 새 사이트에서 교사 로그인 → 백업 불러오기 → JSON 선택.
4. ‘서버 저장됨’을 확인합니다. 불러오기는 서버의 현재 기록을 교체하므로 먼저 백업하세요.

이후의 기록은 서버 PostgreSQL에 저장됩니다. 기록 백업 기능도 그대로 사용할 수 있습니다.

## 비밀번호 변경·분실

- 최초 교사 비밀번호는 Render의 TEACHER_PASSWORD입니다. 학생에게 공유하지 않습니다.
- 기존 화면의 비밀번호 변경을 사용하면 새 비밀번호는 해시로 데이터베이스에 저장됩니다. 평문 비밀번호를 브라우저 저장소에 보관하지 않습니다.
- 기존 질문·답 입력란을 보존했습니다. 질문은 저장하고 답은 해시로 저장하지만, 별도의 공개 비밀번호 복구 화면을 추가하지 않았습니다.
- 화면에서 비밀번호를 바꾼 뒤에는 Render의 TEACHER_PASSWORD만 바꾸어도 기존 DB 비밀번호가 초기화되지는 않습니다.
- 분실하면 데이터베이스 관리 화면의 SQL Editor에서 다음 한 문장을 실행한 뒤 Render의 TEACHER_PASSWORD로 로그인합니다. 학생 기록은 건드리지 않습니다.

    UPDATE exam_app SET password_hash = NULL, recovery_question = NULL, recovery_answer_hash = NULL WHERE id = 1;

## 저장 충돌과 오류

- 서로 다른 학생 제출은 트랜잭션 안에서 해당 학생의 해당 점수 항목만 바꾸므로 다른 학생의 기록을 덮어쓰지 않습니다.
- 같은 학생의 같은 항목을 여러 번 제출하면 마지막 제출 값이 적용됩니다.
- 교사 화면에서 오래된 기록을 저장하려 하면 충돌을 알리고 덮어쓰지 않습니다. 화면의 기록 백업으로 입력 내용을 보관한 뒤 새로고침하여 다시 적용하세요.
- 서버 연결이 실패한 학생 폼은 입력을 유지합니다. 성공 메시지를 보기 전에는 저장된 것으로 간주하지 마세요.
- Render 무료 서버가 쉬고 있으면 첫 접속이 느릴 수 있습니다. 잠시 기다린 뒤 다시 시도하세요.
- 서버 재시작·재배포 후에도 같은 DATABASE_URL을 쓰면 기록을 다시 불러옵니다. 데이터베이스 자체를 삭제하거나 서비스 한도를 넘기는 경우는 별개입니다.

## 로컬 실행 (선택)

Node.js 22와 pnpm을 설치하고, .env.example을 .env로 복사하여 실제 값을 채웁니다. 테스트 전용 PostgreSQL을 사용하는 것이 좋습니다.

    pnpm install --frozen-lockfile
    pnpm start

http://localhost:3000 에 접속합니다. 로컬은 NODE_ENV=development를 사용합니다. 배포에서는 HTTPS와 NODE_ENV=production을 사용합니다.

핵심 검증:

    pnpm test

## 파일 구성과 변경 범위

- original/시험기간_이벤트_통합로그인.html: 전달받은 원본, 바이트 단위로 동일합니다.
- public/index.html: 서버 연결용 사본. 기존 CSS와 화면 구조, 이벤트 내용은 보존했습니다.
- server.mjs: 서버 로그인, 기록 API, PostgreSQL 저장.
- domain.mjs: 기록 검증 및 학생 점수 처리.
- render.yaml: 무료 Render Web Service 설정.
- .env.example: 환경 변수 예시.
- test/domain.test.mjs: 핵심 입력 검증 테스트.
- VERIFICATION.md: 실행한 검증과 범위.

배포용 사본에서는 사실과 달라지는 저장 안내 문구 3곳만 서버 저장 안내로 바꿨습니다. 날짜·시간표·이벤트 설명과 디자인은 수정하지 않았습니다. 서버 연결, 교사 인증, 저장 상태 및 오류 처리 코드는 변경했습니다.

## 참고한 공식 문서

- Render 무료 서비스와 저장 제한: https://render.com/docs/free
- Render Node 웹 서비스: https://render.com/docs/deploy-node-express-app
- Render Node 버전: https://render.com/docs/node-version
- Neon 요금 및 무료 플랜: https://neon.com/pricing
- Neon 연결 안내: https://neon.com/docs/connect/connect-from-any-app

확인일: 2026-09-23. 계정 생성·GitHub 업로드·Render 배포·실제 외부 DB 연결은 사용자가 진행합니다.
