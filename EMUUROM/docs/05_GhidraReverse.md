# 05. Ghidra 리버스 엔지니어링 결과

## 분석 기준

| 항목 | 값 |
|------|-----|
| 대상 파일 | `emuurom_backup.exe` |
| Ghidra 프로그램명 | `emuurom_backup.exe` |
| Image Base | `0x140000000` |
| 함수 수 | 6,611개 |
| 목적 | 한글 glyph 색상 깨짐 원인 확인 |

---

## 렌더링 관련 주요 함수

| 함수 | 역할 |
|------|------|
| `FUN_1400e1c00` | Lua `print` wrapper |
| `FUN_1400df7e0` | Lua `rect` wrapper |
| `FUN_1400ce2b0` | `print` backend |
| `FUN_1400ce3a0` | `rect` backend |
| `FUN_1400cbba0` | bitmap font 문자열 렌더링 루프 |
| `FUN_1400cb6e0` | 사각 영역을 framebuffer에 채움 |
| `FUN_1400d2440` | framebuffer 4bpp nibble 직접 쓰기 |

---

## Lua `print` 경로

`FUN_1400e1c00`은 Lua 인자를 읽고 TIC runtime 객체의 `+0x242b50` 함수 포인터를 호출한다.

해당 포인터는 초기화 함수에서 `FUN_1400ce2b0`로 설정된다.

정리:

```text
Lua print(...)
  -> FUN_1400e1c00
  -> runtime + 0x242b50
  -> FUN_1400ce2b0
  -> FUN_1400cbba0
  -> FUN_1400cb6e0
  -> FUN_1400d2440
```

`FUN_1400ce2b0`은 `param_5` 색을 `local_37`에 넣고, `local_38 = 0xff`와 함께 glyph 렌더링 함수로 전달한다.

중요한 점은 `print` backend에서 Lua `rect`처럼 `0x3FF0` palette remap을 직접 조회하는 코드가 보이지 않는다는 것이다.

---

## 원본 system font 위치

`FUN_1400ce2b0`는 font tilesheet 포인터를 만들 때 runtime RAM의 `+0x14604`를 참조한다.

정리:

```text
system font bitmap base = *(runtime + 0x30) + 0x14604
regular font params     = *(runtime + 0x30) + 0x149fc / +0x149fd
alt font params         = *(runtime + 0x30) + 0x14dfc / +0x14dfd
```

`FUN_1400cbba0` 내부에서는 문자 코드를 font sheet index로 직접 사용해 1bpp font bitmap을 읽는다. 최종 패치 구현도 원본 ASCII row를 `code * 8` 기준으로 재구성한다. 런타임 주소를 직접 `peek`하지 않고, 동일한 원본 TIC-80 system font bitmap을 `emuurom_tool.py` 안에 내장해 `krglyphs`로 합친다. 이렇게 해야 `.py` 교체만으로 다른 환경에서도 같은 결과를 만들 수 있다.

---

## 원본 `font()` skands 경로

원본 `utf8printf`는 `⌘`, `æ`, `ä` 같은 문자를 `skands` table로 변환한 뒤 다음 경로로 그린다.

```lua
bpp(1)
font(skands[char], x, y + y2, 0, 6, 8, fixed, scale)
bpp(4)
```

TIC-80 `font()`는 현재 blit segment를 반전한 tilesheet를 사용한다. `bpp(1)` 상태에서는 foreground bank의 1bpp page 0을 읽으므로, `⌘`는 `skandstr`의 tile 38에서 나온다. 패치 구현은 이 glyph를 `extract`의 bank0 sprites chunk에서 직접 재구성해 `krglyphs`에 넣는다. 확인한 `⌘` bitmap은 `44aa7c287caa4400`이다.

---

## Lua `rect` 경로

`FUN_1400df7e0`은 Lua `rect(x,y,w,h,color)` wrapper이다. 인자 5개를 읽고 runtime 객체의 `+0x242b70` 함수 포인터를 호출한다.

해당 포인터는 `FUN_1400ce3a0`이다.

`FUN_1400ce3a0`의 핵심 동작:

```c
param_6 =
    *(byte *)(((param_6 & 0xf) >> 1) + 0x3ff0 + *(longlong *)(param_1 + 0x30))
    >> (((param_6 & 0xf) & 1) << 2)
    & 0xf;

FUN_1400cb6e0(param_1, x, y, w, h, param_6);
```

즉 `rect`는 색상 인자를 그대로 쓰지 않고, TIC-80 palette 영역 `0x3FF0`의 remap 결과로 바꾼 뒤 그린다.

---

## raw pixel write

`FUN_1400d2440`는 4bpp framebuffer 한 픽셀을 직접 쓴다.

정리된 동작:

```c
if (addr >= 0 && addr < 0x30000) {
    byte* p = framebuffer + (addr >> 1);
    shift = (addr & 1) << 2;
    *p = (*p & ~(0x0f << shift)) | ((color & 0xf) << shift);
}
```

Lua `poke4(addr,val)` wrapper도 이 함수 포인터를 호출한다. 따라서 Lua에서 `poke4(py*240+px,color)`를 사용하면 palette remap을 거치지 않고 직접 픽셀 색을 쓸 수 있다.

---

## 색상 깨짐 버그 원인

### 증상

엔딩 가사에서 위쪽 줄만 초반 1~2박 동안 다음 문제가 발생했다.

- 전체 회색 가사가 잠깐 흰색/빨강/노랑처럼 보임
- 실제 박자보다 먼저 일부 글자가 강조된 것처럼 보임
- 3번째 박자 이후에는 정상처럼 보임

### Lua 쪽 배경

엔딩 이미지 전환 중 `img:drw`는 lyrics보다 먼저 실행된다.

```lua
if E.imgs[E.song][E.part] then
    img:drw(t,E)
end
if E.drwLyrics then
    for j,line in pairs(E.txtQueue) do
        for i,word in ipairs(line) do word:drw(line) end
    end
end
```

`img:drw`는 전환 중 `pal(E.bgcol,E.bgswap)`을 호출할 수 있다. 또 `lighten` shader는 palette를 바꾼다.

### 결론

원본 영어는 TIC `print` 경로를 타므로 이 palette remap 문제를 피한다. 이전 한글 patch는 glyph를 `rect`로 찍었기 때문에 palette remap을 타서 색이 깨졌다.

따라서 수정 방향은 박자 타이밍을 바꾸는 것이 아니라, 한글 glyph 출력 경로를 `rect`에서 `poke4` 직접 쓰기로 바꾸는 것이다.

---

## 현재 수정 상태

현재 `emuurom_tool.py`가 생성하는 `krfont`는 다음 특징을 가진다.

| 항목 | 상태 |
|------|------|
| `rect` glyph 출력 | 사용 안 함 |
| `pix`/`ttri` 임시 bank 출력 | 사용 안 함 |
| `poke4` 직접 출력 | 사용 |
| palette remap 영향 | 회피 |
| test-mode 대상 | `endred2` |

검증한 생성 Lua 조건:

```text
function krrawrect           존재
poke4(py*240+px,color)       존재
rect(x+xx*scale,...)         없음
pix(sx0+xx,sy0+yy,color)     없음
startGam:enter(...,"endred2") test mode에서 존재
```

