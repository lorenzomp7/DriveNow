import zipfile

from tools import app_scan

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.example.lights">
  <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION"/>
  <uses-permission android:name="android.permission.ACCESS_BACKGROUND_LOCATION"/>
  <uses-permission android:name="android.permission.FOREGROUND_SERVICE_LOCATION"/>
  <uses-permission android:name="androidx.car.app.NAVIGATION_TEMPLATES"/>
  <queries><intent><action android:name="android.intent.action.TTS_SERVICE"/></intent></queries>
  <application>
    <meta-data android:name="com.google.android.gms.car.application" android:resource="@xml/automotive_app_desc"/>
    <service android:name=".Nav" android:foregroundServiceType="location" android:exported="false"/>
    <service android:name=".Car" android:exported="true">
      <intent-filter>
        <action android:name="androidx.car.app.CarAppService"/>
        <category android:name="androidx.car.app.category.NAVIGATION"/>
      </intent-filter>
    </service>
  </application>
</manifest>"""


def _decode(sha="ab" * 32):
    return {"subject": {"identity": {"sha256": sha}},
            "normalized_result": {"client": {"apktool_version": "2.12.1"},
                                  "metadata": {"package_name": "com.example.lights", "version_name": "1.2",
                                               "version_code": "12", "min_sdk_version": "26",
                                               "target_sdk_version": "35"},
                                  "manifest": MANIFEST,
                                  "strings": [{"name": "light_ahead", "value": "Ampel in 200 m"},
                                              {"name": "voice_on", "value": "Voice announcements"},
                                              {"name": "unrelated", "value": "Settings"}]}}


def test_manifest_declarations_are_read():
    m = app_scan.parse_manifest(MANIFEST)
    assert m["package"] == "com.example.lights"
    assert "android.permission.ACCESS_BACKGROUND_LOCATION" in m["permissions"]
    assert [(s["name"], s["foreground"]) for s in m["services"] if s["foreground"]] == [(".Nav", "location")]
    assert "android.intent.action.TTS_SERVICE" in m["queries"]
    aa = app_scan.android_auto(m)
    assert any("CarAppService" in what and "NAVIGATION" in what for what, _ in aa)
    assert any("com.google.android.gms.car.application" in what for what, _ in aa)


def test_sheet_has_every_section_and_only_matching_strings(tmp_path):
    apk = tmp_path / "base.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("lib/arm64-v8a/libflutter.so", b"")
        z.writestr("META-INF/androidx.car.app_app.version", b"1.4.0")
    text = app_scan.sheet("Lights", _decode(), None, [str(apk)], "6.10.1", "2.12.1", "test", "2026-11-24")
    for heading in ("## Dati dei semafori", "## Annunci a voce", "## Posizione in background",
                    "## Android Auto", "## Tutti i permessi"):
        assert heading in text
    assert "Flutter (motore)" in text and "androidx.car.app (Android Auto)" in text
    assert "Ampel in 200 m" in text and "Voice announcements" in text
    assert "Settings" not in text
    assert "`ACCESS_BACKGROUND_LOCATION`" in text and "`.Nav` (location)" in text


def test_apks_and_evidence_must_stay_outside_the_repository(tmp_path):
    import pytest

    with pytest.raises(SystemExit):
        app_scan.main(["docs/x.apk", "--app", "X", "--evidence-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        app_scan.main([str(tmp_path / "x.apk"), "--app", "X", "--evidence-dir", "docs/evidence"])
