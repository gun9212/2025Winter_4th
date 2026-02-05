# Google Drive ID 마이그레이션 및 직접 링크 연동 가이드

## 1. 배경 및 목적
기존 시스템은 파일을 다운로드할 때 로컬 파일 경로(예: `local:폴더/파일.pdf`)를 `drive_id`로 사용했습니다. 이로 인해 프론트엔드에서 문서 제목을 클릭했을 때 **Google Drive 원본 문서로 바로 이동하지 못하는 문제**가 있었습니다.

이를 해결하기 위해 `drive_id`를 실제 **Google Drive File ID**(예: `1cXcc...`)로 전환하는 작업을 진행합니다.

## 2. 시스템 변경 사항

### Backend Logic (`step_01_ingest.py`)
- **기존**: `rclone sync` 후 단순히 파일 경로를 ID로 사용.
- **변경**: `rclone sync` 후 `rclone lsjson` 명령어를 추가로 실행하여, **실제 Drive ID**를 조회하고 이를 DB에 저장하도록 개선했습니다.
- **효과**: 앞으로 수집되는 모든 문서는 올바른 Drive ID를 갖게 됩니다.

### Scripts
- `scripts/migrate_drive_ids.py`: 기존 DB의 문서 ID를 실제 Drive ID로 일괄 업데이트하는 도구.
- `scripts/rollback_drive_ids.py`: 문제 발생 시 백업 파일을 이용해 즉시 원상복구하는 도구.

## 3. 마이그레이션 실행 가이드 (서버 작업)

이 작업은 서버의 `backend` 컨테이너 또는 환경에서 실행해야 합니다.

### 단계 1: 코드 업데이트 및 재시작
먼저 최신 코드를 서버에 반영합니다.
```bash
cd ~/Molip/week4/backend
git pull
# Ingestion 로직 변경 사항 반영을 위해 재시작 권장
docker compose restart backend
```

### 단계 2: 마이그레이션 시뮬레이션 (Dry Run)
실제 DB를 건드리지 않고, 어떤 ID가 어떻게 바뀔지 미리 확인합니다.
```bash
# 쉘 진입 (docker 사용하는 경우)
docker compose exec backend bash

# 스크립트 실행
python scripts/migrate_drive_ids.py --dry-run
```
*출력 로그에서 `[DRY RUN] Would update...` 메시지를 확인하세요.*

### 단계 3: 실제 마이그레이션 실행
**주의**: 실행 직전 자동으로 `backend/backup/` 폴더에 현재 DB 상태가 백업됩니다.
```bash
python scripts/migrate_drive_ids.py
```
*성공적으로 완료되면 `Migration committed` 로그가 출력됩니다.*

## 4. 롤백 가이드 (비상 시)

마이그레이션 후 치명적인 문제가 발견되면 즉시 롤백합니다.

1. **백업 파일 확인**: `backend/backup/` 폴더에 생성된 `drive_id_backup_날짜.json` 파일을 찾습니다.
2. **롤백 실행**:
```bash
python scripts/rollback_drive_ids.py --backup-file backup/drive_id_backup_20250205_xxxx.json
```
*프롬프트에서 `y`를 입력하면 즉시 복원됩니다.*

## 5. 검증 방법

1. **웹 인터페이스 접속**: 구글 시트 채팅 화면 새로고침.
2. **문서 클릭**: 검색 결과(Reference)에 나온 문서 제목 클릭.
3. **확인**: Google Drvie 미리보기 또는 수정 화면으로 **새 탭에서 바로 이동**하는지 확인. (더 이상 검색 화면이 아님)

## 6. 안전성 검토 결과
- **파일 처리 영향 없음**: 시스템은 파일 내용을 읽거나 처리할 때 `drive_id`가 아닌 `drive_path`(로컬 경로)를 사용하므로, ID가 바뀌어도 **기존 파이프라인(파싱, 임베딩 등)은 정상 작동**합니다.
- **중복 데이터**: 혹시라도 ID 중복이 발생하면 스크립트가 경고 로그를 남기며, 이는 데이터 무결성을 위해 바람직한 동작입니다.
