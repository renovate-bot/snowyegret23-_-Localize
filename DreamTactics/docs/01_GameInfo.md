# 01. 게임 기본 정보

## 게임 기본

| 항목 | 내용 |
|------|------|
| **게임명** | Dream Tactics |
| **개발사** | Spectra Entertainment |
| **엔진** | 자체 엔진 (커스텀) - Unity/Unreal 아님 |
| **장르** | 턴제 전략 RPG (카드 기반) |
| **실행 파일** | `Dream.exe` |
| **아키텍처** | x86-64 (64비트) |
| **파일 포맷** | PE (Portable Executable) |
| **그래픽 API** | OpenGL 3.1+ |
| **오디오** | Ogg Vorbis (커스텀 래퍼, `.redfishsound`) |
| **데이터 관리** | 해시 기반 에셋 시스템 |
| **압축** | LZHAM (`dict_size_log2 = 18`) |

---

## 경로 정보

### 게임 설치 경로 (GOG 기준)
```
C:/GOG Games/Dream Tactics/
├── Dream.exe              # 메인 실행 파일
├── data/                  # 에셋 폴더
│   ├── 0                  # 인덱스 파일 (32,500 bytes)
│   ├── 515357558          # locale/english.json (압축됨)
│   ├── 2946173491         # locale/japanese.json (압축됨)
│   ├── 3584817163         # locale/chinese.json (압축됨)
│   └── ...                # 총 2,710개의 에셋 파일
└── licenses/              # 라이센스 (Pretendard 포함)
    ├── pretendard.txt
    ├── noto.txt
    ├── misaki.txt
    └── fusion.txt
```

### 사용자 데이터 경로
```
C:/Users/<USER>/AppData/Roaming/Spectra Entertainment/Dream Tactics/
├── options.json           # 게임 설정 (★언어 설정 포함)
├── meta.save              # 메타 세이브 데이터 (바이너리)
├── game.log               # 게임 로그
├── combat.log             # 전투 로그
└── party.log              # 파티 로그
```

---

## PE 파일 분석 (Dream.exe)

### 기본 정보
| 항목 | 값 |
|------|-----|
| **Image Base** | `0x140000000` |
| **Min Address** | `0x140000000` |
| **Max Address** | `0xff0000184f` |
| **총 함수 수** | 19,508개 |
| **Language ID** | x86:LE:64:default |

### PE 섹션 테이블
| 섹션 | VMA (가상 주소) | 파일 오프셋 | 크기 | 속성 |
|------|-----------------|-------------|------|------|
| `.text` | `0x140001000` | `0x00000400` | `0x005b5f94` | CODE, READONLY |
| `.rdata` | `0x1405b7000` | `0x005b6400` | `0x0021d476` | DATA, READONLY |
| `.data` | `0x1407d5000` | `0x007d3a00` | `0x00021600` | DATA |
| `.pdata` | `0x1408c0000` | `0x007f5000` | `0x0004b42c` | DATA, READONLY |
| `_RDATA` | `0x14090c000` | `0x00840600` | `0x00000b50` | DATA, READONLY |
| `.gehcont` | `0x14090d000` | `0x00841200` | `0x00000028` | DATA, READONLY |
| `.rsrc` | `0x14090e000` | `0x00841400` | `0x00019c18` | DATA, READONLY |
| `.reloc` | `0x140928000` | `0x0085b200` | `0x00004b38` | DATA, READONLY |

### VMA ↔ 파일 오프셋 변환 공식

`.rdata` 섹션 기준 (대부분의 문자열이 여기 있음):

```python
def file_to_vma(file_offset):
    if file_offset >= 0x5b6400:
        return file_offset - 0x5b6400 + 0x1405b7000
    return None

def vma_to_file(vma):
    if vma >= 0x1405b7000:
        return vma - 0x1405b7000 + 0x5b6400
    return None
```

---

## 주요 Import 라이브러리

| DLL | 용도 |
|-----|------|
| `WS2_32.DLL` | 네트워크 (멀티플레이어) |
| `OPENGL32.DLL` | 그래픽 렌더링 |
| `USER32.DLL` | 윈도우/입력 처리 |

### 주요 OpenGL 함수
- `glDrawArrays`, `glDrawElements` - 렌더링
- `glTexImage2D`, `glTexSubImage2D` - 텍스처
- `wglGetProcAddress` - GL 확장 로딩

---

## options.json 전체 구조

```json
{
    "version": 5,
    "keyboard_controls": { /* 키보드 매핑 */ },
    "controller_controls": { /* 컨트롤러 매핑 */ },
    "mousekeyboard_controls": { /* 마우스+키보드 매핑 */ },
    "gameSettings": {
        "battleSpeed": 1,
        "language": 0,                              // ★ 0=en, 1=ja, 2=zh
        "masterVolume": 10,
        "musicVolume": 10,
        "sfxVolume": 10,
        "ambienceVolume": 10,
        "automaticallyEndTurnWhenWaitingAllPlayers": true,
        "showCardRangeWhenMoving": false,
        "calculateHealthDifferenceInUnitPanel": false,
        "promptTurnEndConfirm": true,
        "disableMouseMode": false,
        "disableMouseGrab": true,
        "disableMouseHide": false,
        "disableToolTips": false,
        "disableEnemyAggroTint": false,
        "disableTutorials": false,
        "zoom": false,
        "autoVN": false,
        "shrinkUnitPanelIfNoEffects": true,
        "quickMove": false,
        "quickCards": false,
        "usePixelFont": true,                       // ★ 픽셀 폰트
        "skipSplash": false,
        "video": {
            "brightness": 5,
            "displayMode": 0,
            "fullscreen": true,
            "force60Hz": false
        }
    }
}
```

---

## 게임 내 하드코딩 문자열

### 핵심 문자열 주소
| 문자열 | VMA | 용도 |
|--------|-----|------|
| `"Dream Tactics"` | `0x1405b9c68` | 게임 제목 |
| `"Spectra Entertainment"` | `0x1405b9c78` | 개발사 |
| `"Loading Level: %s"` | `0x1405ba248` | 레벨 로딩 로그 |
| `"Game Over"` | `0x1405ba290` | 게임 오버 |
| `"Loaded Session Save"` | `0x1405ba360` | 세이브 로드 |
| `"DreamTactics"` | `0x1405ba3e8` | 내부 ID |

### 입력 모드 문자열
| 문자열 | VMA |
|--------|-----|
| `"Input Mode: Controller"` | `0x1405ba2e0` |
| `"Input Mode: Keyboard"` | `0x1405ba2f8` |
| `"Input Mode: Mouse and Keyboard"` | `0x1405ba310` |

### 커맨드라인 옵션
| 플래그 | VMA |
|--------|-----|
| `-noMouseMode` | `0x1405b9bf0` |
| `-noMouseHide` | `0x1405b9c00` |
| `-noTurnEndPopup` | `0x1405b9c10` |
| `-noToolTips` | `0x1405b9c20` |
| `-noBugSplat` | `0x1405ba3c8` |

### 로그 파일명
| 파일명 | VMA |
|--------|-----|
| `game.log` | `0x1405ba218` |
| `party.log` | `0x1405ba228` |
| `combat.log` | `0x1405ba238` |

---

## VN (비주얼 노벨) / 대화 시스템

### 스크립트 명령어
```
StartVNSegment(stringId)
StartVNSegment(stringId, bool)
Text(stringId)
Enter(stringId)
Enter(stringId, stringId)
Enter(stringId, stringId, stringId)
Enter(stringId, stringId, stringId, stringId)
EnterLite(stringId, *)
Exit(stringId, stringId)
ExitAll()
```

### 에러 메시지 (디버깅용)
```
"Incorrect args for Text(stringId)"
"Incorrect args for StartVNSegment(string)"
"Incorrect args for StartVNSegment(string, bool)"
"Incorrect Argument::List for Enter(stringId)."
"Incorrect Argument::List for EnterLite(stringId, *)."
"Invalid VNAction: %s"
"Expected to be in VN mode: %s"
"Expected to be in Default mode: %s"
"Invalid syntax in line: %s"
"Argument mismatch in line: %s"
"Parenthesis mismatch in line: %s"
"Quotation mismatch in line: %s"
"Invalid opcode in line: %s"
"Malformed number \"%s\" in line: %s"
```

---

## 오디오 시스템

### 음악 파일 경로
```
"audio/music/"           # 기본 경로
".redfishsound"          # 파일 확장자
```

### 사운드 이벤트 예시
```
# 앰비언스
ambience_ashguard_outside_loop
ambience_castle_loop
ambience_cave_loop
ambience_coral_loop

# 원샷 효과음
oneshot_gameover
oneshot_door
oneshot_chest
oneshot_save

# UI 사운드
ui_accept
ui_click
ui_deny
ui_text
ui_level_up
```

---

## 게임 데이터 구조

### 엔티티 경로
```
"entities/players/"      # 플레이어 캐릭터
"entities/enemies/"      # 적 캐릭터
"entities/other/"        # 기타 엔티티
```

### 프로필/스프라이트
```
"_profile.texture"       # 프로필 텍스처
"_profile.spritesheet"   # 스프라이트시트
".texture"
".spritesheet"
"%i_Portrait0"           # 초상화
```

### 캐릭터/필로우 타입 (100개 이상)
```
angelpillow, archerpillow, assassinpillow
bellpillow, bombpillow, guardpillow
healerpillow, heropillow, kingpillow
magepillow, mechpillow, medicpillow
...
```

### 카드 시스템 (100개 이상)
```
cards_arson, cards_assassinate, cards_assault
cards_blizzard, cards_bloom, cards_charge
cards_charm, cards_clone, cards_decay
cards_dream, cards_earthquake, cards_finale
...
```

### 스토리/스크립트
```
dreamScriptAssetId
startCutsceneDreamScriptAssetId
rosieConsumeDreamScriptAssetId
additionDreamScriptAssets

Starting Encounter: %s
Finished Encounter
nextLevelName
nextLevelNameId
levelNameId
currentEncounterIndex
finishedEncounters

storyItemId
storyItems
usedStoryItems
m_storyItemId
```

### 폰트 관련 (FreeType 메타데이터)
```
postscript-font-name
fallback-script
default-script
glyph-to-script-map
```
