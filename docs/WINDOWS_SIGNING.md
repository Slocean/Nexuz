# Windows 代码签名（可选）

> **当前热更新不依赖 Authenticode。**  
> 客户端只校验固定 GitHub Release 地址 + `Nexuz.exe.sha256`。  
> Release CI **默认不签名**，也不再要求 `WINDOWS_CERTIFICATE` Secrets。

未签名的 `Nexuz.exe`（尤其是 PyInstaller 打包）仍可能被 Windows Defender / SmartScreen 拦截。  
若以后需要降低误报，可自行购买 OV/EV 代码签名证书并用本目录脚本本地签名；这与自动更新无关。

## 本地签名（可选）

```powershell
.\scripts\new_codesign_cert.ps1
python package.py
.\scripts\sign_exe.ps1 -ExePath dist\Nexuz.exe -PfxPath .codesign\nexuz-codesign.pfx -Password "你的密码"
```

注意：`.codesign/`、`*.pfx` 不要提交进 git。
