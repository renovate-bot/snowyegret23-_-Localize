# 04. 한글 폰트 / Unicode 렌더링 패치

## 목적

원본 TIC-80 폰트 경로는 한글 glyph를 포함하지 않는다. 도구는 `Galmuri7.ttf`에서 필요한 문자를 8x8 bitmap으로 추출하고, Lua 코드 안에 `krglyphs`, `krwidth`, `krhanguls`, `krfont`를 삽입한다.

---

## glyph 생성

기본값:

| 항목 | 값 |
|------|-----|
| `KRFONT_SOURCE_SIZE` | `8` |
| `KRFONT_DRAW_SIZE` | `8` |
| `KRFONT_THRESHOLD` | `80` |
| 기본 폰트 | `Galmuri7.ttf` |

처리 순서:

1. `collect_krfont_chars`가 패치된 Lua 코드에서 필요한 문자를 수집한다.
2. `glyph_rows`가 PIL로 TTF glyph를 grayscale bitmap으로 렌더링한다.
3. threshold 이상 픽셀을 1비트 bitmap으로 만든다.
4. 각 문자의 실제 너비를 `krwidth`에 저장한다.
5. 한글 문자는 `krhanguls`에 등록한다.

---

## Lua 삽입 위치

`patch_unicode_renderer`는 `skands=utf8enumerate(skandstr)` 뒤에 한글 glyph block을 삽입한다.

삽입되는 주요 전역:

| 이름 | 의미 |
|------|------|
| `krsrcw` | 원본 glyph 폭 |
| `krsrch` | 원본 glyph 높이 |
| `krdraw` | 출력 glyph 크기 |
| `krhex` | 한 행 hex 길이 |
| `krglyphs` | 문자별 bitmap rows |
| `krwidth` | 문자별 실제 폭 |
| `krhanguls` | 한글 문자 set |
| `krfont` | 한글 glyph 출력 함수 |

---

## krmode

원본 `utf8printf`는 문자별로 TIC-80 `print`, 특수 문자, 스칸디나비아 glyph 등을 분기한다.

패치 후에는 `fulltext or text`에 한글이 하나라도 있으면 `krmode=true`가 된다.

```lua
local krmode=false
if krhanguls then
    for krc in pairs(utf8enumerate(fulltext or text)) do
        if krhanguls[krc] then krmode=true break end
    end
end
```

그 뒤 `krmode`가 켜진 줄에서는 한글 patch glyph가 있는 문자만 `krfont`로 그린다.

---

## 현재 렌더링 방식

현재 `krfont`는 `rect`, `pix`, `ttri`를 사용하지 않고 `poke4`로 화면 framebuffer에 직접 픽셀을 쓴다.

핵심 루틴:

```lua
function krrawrect(x,y,scale,color)
    x=x//1
    y=y//1
    for sy=0,scale-1 do
        local py=y+sy
        if py>=0 and py<136 then
            for sx=0,scale-1 do
                local px=x+sx
                if px>=0 and px<240 then poke4(py*240+px,color) end
            end
        end
    end
end
```

이 방식은 `rect`의 palette remap 경로를 피하기 위해 사용한다. 근거는 [05_GhidraReverse.md](05_GhidraReverse.md)에 정리되어 있다.

---

## 왜 `rect`를 쓰지 않는가

처음 구현은 한글 glyph의 각 픽셀을 `rect(x,y,scale,scale,color)`로 출력했다. 그러나 원본 `emuurom_backup.exe`를 Ghidra로 확인한 결과, `rect` backend는 `0x3FF0` palette remap 테이블을 거친다.

엔딩 이미지 전환 중에는 Lua 쪽에서 `pal(E.bgcol,E.bgswap)`과 `lighten` shader가 동작한다. 이때 `rect`로 그린 한글 glyph만 palette remap 영향을 받아 회색 가사가 빨강/노랑/흰색처럼 보였다.

`poke4`는 framebuffer nibble을 직접 쓰므로 이 문제를 피한다.

---

## 같이 적용되는 패치

`patch-unicode`는 glyph 삽입 외에도 다음 패치를 함께 적용한다.

| 패치 | 목적 |
|------|------|
| `newlines` 교체 | 한글 폭 기준 줄바꿈 |
| `endred2` karaoke width 교체 | 원본 박자 로직 유지 + 한글 폭 계산 |
| PC terminal cursor 교체 | 고정 6픽셀 계산 대신 현재 줄 실제 폭 사용 |

---

## PC terminal cursor

원본 커서 위치 계산은 `w_char = LANG==LANGS.JP and 8 or 6` 기준이다. 한글이 들어가면 실제 출력 폭과 커서 위치가 어긋난다.

패치 후에는 현재 줄 텍스트의 폭을 `getcenterwidth(cursorText,true,1,false)`로 계산해 커서를 배치한다.

---

## 주의 사항

- `Galmuri7.ttf`는 게임 루트에 있어야 한다.
- 번역문에 새 문자가 추가되면 다시 `python emuurom_tool.py import` 또는 `patch-unicode`를 실행해야 한다.
- `threshold`를 바꾸면 glyph 굵기와 누락 픽셀이 달라진다.
- `draw-size`를 `source-size`와 다르게 쓰면 별도 축소/확대 branch가 사용된다.

