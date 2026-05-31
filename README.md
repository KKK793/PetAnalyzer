<img width="1614" height="1231" alt="a68968070c50685e7fe0b512e1aa0c32" src="https://github.com/user-attachments/assets/cca804d7-75f6-4a7b-9756-5201881a3188" /># PetAnalyzer

精灵鉴定器，用于识别《洛克王国：世界》桌面端窗口中的精灵鉴定界面，并根据 `data/pet_plans.json` 计算培养道具消耗。

## 当前形态

- 识别目标为游戏进程 `NRC-Win64-Shipping.exe`。
- 支持后台窗口捕获，但游戏窗口不能最小化。

## 运行

```powershell
.\.venv\Scripts\python.exe desktop_float.py
```

## 构建

```powershell
.\build_float_desktop.bat
.\build_inno_installer.bat
```

输出：

```text
dist\PetAnalyzer\PetAnalyzer.exe
dist\PetAnalyzerSetup.exe
```

## 框选识别位置
<img width="1614" height="1231" alt="a68968070c50685e7fe0b512e1aa0c32" src="https://github.com/user-attachments/assets/741a0d0a-26d1-42ec-855c-3176e7b897c4" />

## 已配置框选分辨率

- 640x480
- 720x480
- 720x576
- 800x600
- 1024x768
- 1152x864
- 1176x664
- 1280x720
- 1280x768
- 1280x800
- 1280x960
- 1360x768
- 1366x768
- 1440x900
- 1440x1080
- 1600x900
- 1600x1200
- 1680x1050
- 1920x1080
- 1920x1200
- 1920x1440
- 2048x1152
- 2048x1536
- 2560x1080
- 2560x1440
- 2560x1600
- 3440x1440
- 3840x2160

## 识别内容

- 特性文字，用于匹配 `pet_plans.json` 中的 `特性` 字段。
- 绿色向上箭头对应的性格增益。
- 红色向下箭头对应的性格减益。
- 白条后面的黄色 `+数字` 个体值加成。
- 特性只用于匹配精灵，精灵名称区域只显示匹配到的名称。

## 计算规则

- 残缺魔镜只修改性格减益。
- 适格钥匙优先，用于添加或移动一个基础个体加成为 `8` 的词条。
- 能力钥匙用于把目标个体加成补到当前星级对应满值。
