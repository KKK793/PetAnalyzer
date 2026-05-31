# PetAnalyzer

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

## 分辨率设置
<img width="1614" height="1231" alt="7827ccf0-d426-41a4-bcc0-57c4f3fcb125" src="https://github.com/user-attachments/assets/1e38ade8-61af-42ea-9415-d010dd5917a2" />


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
