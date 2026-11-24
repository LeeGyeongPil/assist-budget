# 보안 정책 / Security policy

보안 취약점을 발견하셨다면 **공개 이슈 대신** 이 레포의 **Security → Report a vulnerability**(비공개 취약점 신고)로 알려 주세요. 확인 후 답변드리고, 고친 버전을 릴리스하면서 함께 안내합니다.

If you find a security issue, please **do not open a public issue**. Use **Security → Report a vulnerability** in this repository to report it privately. We will reply after checking and announce the fix with a release.

## 이 도구가 다루는 것 / What this tool handles

`assist-budget` 은 어떤 포트도 열지 않는 CLI 입니다(`demo` 의 프로세스 내부 가짜 서버만 127.0.0.1 에 잠시 뜹니다). `apply`·`undo` 에서만 내 Home Assistant 에 관리자 토큰으로 접속합니다.

- `.storage` 는 읽기 전용으로만 엽니다.
- 토큰은 환경 변수(`HA_TOKEN`)에서만 읽고, 출력·로그·계획 파일·되돌리기 파일에 쓰지 않습니다.
- `ws://` 는 토큰을 암호화 없이 보냅니다. 믿을 수 있는 LAN 밖에서는 `wss://` 를 쓰세요.

`assist-budget` is a CLI that listens on no port (only the demo's in-process fake server briefly binds 127.0.0.1). Only `apply` and `undo` connect to your Home Assistant, using an administrator token.

- `.storage` is opened read-only.
- The token is read only from the environment variable (`HA_TOKEN`) and is never printed, logged, or written to plan or undo files.
- `ws://` sends the token unencrypted. Outside a trusted LAN, use `wss://`.
