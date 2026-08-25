# 플랫폼 Flutter 앱 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 세로 피드·필터 토글·광 노출 대시보드·업로드가 동작하는 Flutter 앱 (Android 우선, 목업 다크 테마).

**Architecture:** Riverpod 상태관리 + dio API 클라이언트. 서버(`docs/superpowers/plans/2026-08-20-platform-server.md`)의 REST 계약을 소비한다. 피드는 세로 PageView, 영상은 video_player 로 스트리밍(Range), 시청 이벤트 응답으로 노출 배너를 갱신한다.

**Tech Stack:** Flutter stable(3.x), flutter_riverpod, dio, video_player, fl_chart, image_picker, flutter_secure_storage.

**스펙:** `docs/superpowers/specs/2026-08-20-platform-mvp-design.md` · 선행: 서버 계획 완료(로컬 compose 로 api 기동 가능)

## Global Constraints

- 코드는 전부 `app/` (Flutter 프로젝트 루트). 브랜치 `platform-mvp`.
- Android 우선. `API_BASE`는 `--dart-define=API_BASE=...` (기본 `http://10.0.2.2:8000` = 에뮬레이터의 호스트). HTTP 이므로 `android:usesCleartextTraffic="true"` 필수.
- 다크 테마 고정. 팔레트: 배경 `#0A0A0F`, 카드 `#14141B`, 포인트 블루 `#3B6CFF`, 경고 앰버 `#FFB020`, 위험 레드 `#FF4D5E`, 본문 `#FFFFFF`, 보조 `#9AA0AC`.
- 상태 라벨 한글 표기: good→양호, caution→주의, warning→경고.
- 배너 조건: `percent >= 80 && !filterOn` (스펙 3절).
- 시청 이벤트: 페이지를 벗어날 때(스와이프·화면 이탈) 직전 영상에 대해 1건 전송, `watched_s`는 해당 페이지에 머문 초(스톱워치, 600초 상한).
- 소셜: 좋아요만 동작. 댓글·공유·리믹스 버튼은 보이되 탭하면 SnackBar "준비 중".
- 테스트 실행: `cd app && flutter test`.

## API 계약 (서버 계획과 동일 — 요약)

```
POST /auth/signup {email,password,nickname} → 201 {token, user{id,email,nickname}}
POST /auth/login {email,password} → {token, user} / GET /me
GET/PUT /me/settings {filter_on, auto_skip}
GET /me/videos → {videos:[{id,title,status,risk,thumb_url,duration_s,view_count,like_count,created_at}]}
POST /videos multipart(file,title) → 202 {video_id}
GET /feed?cursor=&limit= → {videos:[FeedVideo], next_cursor}
  FeedVideo {id,title,uploader_nickname,risk,variant,stream_url,thumb_url,
             duration_s,like_count,view_count,liked_by_me,stimulus{flash,red,pattern,cut}}
GET /videos/{id}/stream?variant= (Range, Bearer 필요) · GET /videos/{id}/thumb
POST/DELETE /videos/{id}/like → {like_count, liked}
POST /videos/{id}/events {watched_s,variant} → {today_percent, status}
GET /dashboard/today → {risky_views,exposure_s,percent,status,budget_s,
                        stimulus{...}, curve:[{hour,percent}]}
GET /dashboard/weekly → {days:[{date,risky_views}], avg}
```

## 파일 구조

```
app/
  pubspec.yaml
  android/app/src/main/AndroidManifest.xml   # cleartext + 권한
  lib/
    main.dart            # ProviderScope + MaterialApp + 인증 게이트
    theme.dart
    logic/banner.dart    # 배너 판단 순수 함수
    api/client.dart      # dio + 토큰 인터셉터 + 전 엔드포인트
    api/models.dart
    state/auth.dart  state/settings.dart  state/feed.dart  state/exposure.dart
    screens/login.dart  screens/shell.dart  screens/feed.dart
    screens/dashboard.dart  screens/upload.dart  screens/mypage.dart
    widgets/video_page.dart  widgets/action_rail.dart
    widgets/settings_sheet.dart  widgets/warning_banner.dart
  test/banner_test.dart  test/models_test.dart
```

---

### Task F1: Flutter SDK 설치 + 프로젝트 스캐폴드 + 테마

**Files:**
- Create: `app/` (flutter create), `app/lib/theme.dart`, Modify: `app/pubspec.yaml`, `app/lib/main.dart`, `app/android/app/src/main/AndroidManifest.xml`

**Interfaces:**
- Produces: `theme.appTheme` (ThemeData), `theme.AppColors` (bg/card/blue/amber/red/sub 정적 색). 실행 가능한 빈 앱.
- Consumes: 없음

- [ ] **Step 1: Flutter SDK 설치 (Windows)**

```powershell
git clone -b stable --depth 1 https://github.com/flutter/flutter.git C:\src\flutter
# PATH 에 C:\src\flutter\bin 추가 (사용자 환경변수) 후 새 터미널에서:
flutter doctor
```
Android toolchain 이 없으면 Android Studio 설치 → SDK+Platform-Tools 설치 → `flutter doctor --android-licenses` 전부 동의. `flutter doctor`에서 Android toolchain ✓ 확인. (기기: 실기기 USB 디버깅 또는 에뮬레이터 1대 준비)

- [ ] **Step 2: 프로젝트 생성 + 의존성**

```bash
cd gumchulgi && flutter create --org com.gumchulgi --project-name gumchulgi_app app
```

`app/pubspec.yaml` dependencies 를 다음으로 교체:
```yaml
dependencies:
  flutter: { sdk: flutter }
  flutter_riverpod: ^2.6.1
  dio: ^5.7.0
  video_player: ^2.9.2
  fl_chart: ^0.69.0
  image_picker: ^1.1.2
  flutter_secure_storage: ^9.2.2
```
Run: `cd app && flutter pub get` → 성공 확인.

- [ ] **Step 3: AndroidManifest 수정**

`app/android/app/src/main/AndroidManifest.xml`의 `<application` 태그에 `android:usesCleartextTraffic="true"` 추가, `<manifest>` 바로 아래에 `<uses-permission android:name="android.permission.INTERNET"/>` 추가.

- [ ] **Step 4: theme.dart + main.dart**

`app/lib/theme.dart`:
```dart
import 'package:flutter/material.dart';

class AppColors {
  static const bg = Color(0xFF0A0A0F);
  static const card = Color(0xFF14141B);
  static const blue = Color(0xFF3B6CFF);
  static const amber = Color(0xFFFFB020);
  static const red = Color(0xFFFF4D5E);
  static const sub = Color(0xFF9AA0AC);
}

final appTheme = ThemeData(
  brightness: Brightness.dark,
  scaffoldBackgroundColor: AppColors.bg,
  colorScheme: const ColorScheme.dark(
    primary: AppColors.blue, surface: AppColors.card, error: AppColors.red),
  useMaterial3: true,
);
```

`app/lib/main.dart` (게이트는 F4 에서 교체):
```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'theme.dart';

void main() => runApp(const ProviderScope(child: App()));

class App extends StatelessWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: '검출기', theme: appTheme,
        home: const Scaffold(body: Center(child: Text('검출기 플랫폼'))));
}
```

- [ ] **Step 5: 빌드 확인 후 커밋**

Run: `cd app && flutter analyze && flutter test` (기본 위젯 테스트는 삭제: `rm test/widget_test.dart`) → analyze 경고 0
```bash
git add app/
git commit -m "Flutter 스캐폴드 — 다크 테마·의존성·cleartext 설정"
```

---

### Task F2: 모델 + 배너 로직 (TDD)

**Files:**
- Create: `app/lib/api/models.dart`, `app/lib/logic/banner.dart`
- Test: `app/test/models_test.dart`, `app/test/banner_test.dart`

**Interfaces:**
- Produces: `User`, `AppSettings(filterOn, autoSkip)`, `FeedVideo`, `MyVideo`, `Exposure(percent, status)`, `DashboardToday(curve: List<CurvePoint>)`, `Weekly(days: List<DayCount>, avg)` — 전부 `fromJson` 팩토리 / `shouldShowBanner({required double? percent, required bool filterOn}) -> bool`
- Consumes: 없음

- [ ] **Step 1: 실패하는 테스트 작성**

`app/test/banner_test.dart`:
```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:gumchulgi_app/logic/banner.dart';

void main() {
  test('80% 이상 + 필터 OFF 에서만 배너', () {
    expect(shouldShowBanner(percent: 86, filterOn: false), true);
    expect(shouldShowBanner(percent: 86, filterOn: true), false);
    expect(shouldShowBanner(percent: 79.9, filterOn: false), false);
    expect(shouldShowBanner(percent: null, filterOn: false), false);
  });
}
```

`app/test/models_test.dart`:
```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:gumchulgi_app/api/models.dart';

void main() {
  test('FeedVideo.fromJson', () {
    final v = FeedVideo.fromJson({
      'id': 3, 'title': '불꽃', 'uploader_nickname': '박', 'risk': 'corrected',
      'variant': 'filtered', 'stream_url': '/videos/3/stream?variant=filtered',
      'thumb_url': '/videos/3/thumb', 'duration_s': 12.5, 'like_count': 2,
      'view_count': 9, 'liked_by_me': true,
      'stimulus': {'flash': 6, 'red': 4, 'pattern': 3, 'cut': 1},
    });
    expect(v.variant, 'filtered');
    expect(v.stimulus['flash'], 6);
    expect(v.likedByMe, true);
  });

  test('DashboardToday.fromJson', () {
    final d = DashboardToday.fromJson({
      'risky_views': 7, 'exposure_s': 138.0, 'percent': 86.0,
      'status': 'warning', 'budget_s': 160,
      'stimulus': {'flash': 6, 'red': 4, 'pattern': 3, 'cut': 1},
      'curve': [{'hour': 9, 'percent': 40.0}],
    });
    expect(d.percent, 86.0);
    expect(d.curve.first.hour, 9);
  });
}
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd app && flutter test`
Expected: FAIL (파일 없음)

- [ ] **Step 3: 구현**

`app/lib/logic/banner.dart`:
```dart
bool shouldShowBanner({required double? percent, required bool filterOn}) =>
    percent != null && percent >= 80 && !filterOn;
```

`app/lib/api/models.dart`:
```dart
class User {
  final int id; final String email, nickname;
  User({required this.id, required this.email, required this.nickname});
  factory User.fromJson(Map<String, dynamic> j) =>
      User(id: j['id'], email: j['email'], nickname: j['nickname']);
}

class AppSettings {
  final bool filterOn, autoSkip;
  const AppSettings({required this.filterOn, required this.autoSkip});
  factory AppSettings.fromJson(Map<String, dynamic> j) =>
      AppSettings(filterOn: j['filter_on'], autoSkip: j['auto_skip']);
  Map<String, dynamic> toJson() =>
      {'filter_on': filterOn, 'auto_skip': autoSkip};
  AppSettings copyWith({bool? filterOn, bool? autoSkip}) => AppSettings(
      filterOn: filterOn ?? this.filterOn, autoSkip: autoSkip ?? this.autoSkip);
}

class FeedVideo {
  final int id; final String title, uploaderNickname, risk, variant;
  final String streamUrl, thumbUrl;
  final double? durationS;
  final int likeCount, viewCount;
  final bool likedByMe;
  final Map<String, int> stimulus;
  FeedVideo({required this.id, required this.title,
      required this.uploaderNickname, required this.risk,
      required this.variant, required this.streamUrl, required this.thumbUrl,
      required this.durationS, required this.likeCount,
      required this.viewCount, required this.likedByMe,
      required this.stimulus});
  factory FeedVideo.fromJson(Map<String, dynamic> j) => FeedVideo(
      id: j['id'], title: j['title'],
      uploaderNickname: j['uploader_nickname'], risk: j['risk'],
      variant: j['variant'], streamUrl: j['stream_url'],
      thumbUrl: j['thumb_url'],
      durationS: (j['duration_s'] as num?)?.toDouble(),
      likeCount: j['like_count'], viewCount: j['view_count'],
      likedByMe: j['liked_by_me'] == true,
      stimulus: Map<String, int>.from(j['stimulus'] ?? {}));
  FeedVideo copyWith({int? likeCount, bool? likedByMe}) => FeedVideo(
      id: id, title: title, uploaderNickname: uploaderNickname, risk: risk,
      variant: variant, streamUrl: streamUrl, thumbUrl: thumbUrl,
      durationS: durationS, likeCount: likeCount ?? this.likeCount,
      viewCount: viewCount, likedByMe: likedByMe ?? this.likedByMe,
      stimulus: stimulus);
}

class MyVideo {
  final int id; final String title, status; final String? risk;
  final int viewCount, likeCount;
  MyVideo({required this.id, required this.title, required this.status,
      this.risk, required this.viewCount, required this.likeCount});
  factory MyVideo.fromJson(Map<String, dynamic> j) => MyVideo(
      id: j['id'], title: j['title'], status: j['status'], risk: j['risk'],
      viewCount: j['view_count'] ?? 0, likeCount: j['like_count'] ?? 0);
}

class Exposure {
  final double percent; final String status;
  Exposure({required this.percent, required this.status});
  factory Exposure.fromJson(Map<String, dynamic> j) => Exposure(
      percent: (j['today_percent'] as num).toDouble(), status: j['status']);
}

class CurvePoint {
  final int hour; final double percent;
  CurvePoint({required this.hour, required this.percent});
  factory CurvePoint.fromJson(Map<String, dynamic> j) => CurvePoint(
      hour: j['hour'], percent: (j['percent'] as num).toDouble());
}

class DashboardToday {
  final int riskyViews; final double exposureS, percent;
  final String status; final int budgetS;
  final Map<String, int> stimulus; final List<CurvePoint> curve;
  DashboardToday({required this.riskyViews, required this.exposureS,
      required this.percent, required this.status, required this.budgetS,
      required this.stimulus, required this.curve});
  factory DashboardToday.fromJson(Map<String, dynamic> j) => DashboardToday(
      riskyViews: j['risky_views'],
      exposureS: (j['exposure_s'] as num).toDouble(),
      percent: (j['percent'] as num).toDouble(), status: j['status'],
      budgetS: j['budget_s'],
      stimulus: Map<String, int>.from(j['stimulus']),
      curve: (j['curve'] as List)
          .map((e) => CurvePoint.fromJson(e)).toList());
}

class DayCount {
  final String date; final int riskyViews;
  DayCount({required this.date, required this.riskyViews});
  factory DayCount.fromJson(Map<String, dynamic> j) =>
      DayCount(date: j['date'], riskyViews: j['risky_views']);
}

class Weekly {
  final List<DayCount> days; final double avg;
  Weekly({required this.days, required this.avg});
  factory Weekly.fromJson(Map<String, dynamic> j) => Weekly(
      days: (j['days'] as List).map((e) => DayCount.fromJson(e)).toList(),
      avg: (j['avg'] as num).toDouble());
}
```

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

Run: `cd app && flutter test` → PASS
```bash
git add app/
git commit -m "앱 모델·배너 판단 로직 — 파싱 단위 테스트"
```

---

### Task F3: API 클라이언트

**Files:**
- Create: `app/lib/api/client.dart`

**Interfaces:**
- Consumes: `models.dart`
- Produces: `ApiClient` — 메서드: `signup/login -> (String token, User)`, `me() -> User`, `getSettings/putSettings(AppSettings)`, `feed({int? cursor}) -> (List<FeedVideo>, int? nextCursor)`, `like(id)/unlike(id) -> (int likeCount, bool liked)`, `sendEvent(id, watchedS, variant) -> Exposure`, `dashboardToday() -> DashboardToday`, `dashboardWeekly() -> Weekly`, `myVideos() -> List<MyVideo>`, `upload(path, title, onProgress) -> int videoId` / `absoluteUrl(String path) -> String`, `authHeaders -> Map<String,String>` (video_player 용) / riverpod `apiProvider`

- [ ] **Step 1: 구현**

`app/lib/api/client.dart`:
```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'models.dart';

const apiBase = String.fromEnvironment('API_BASE',
    defaultValue: 'http://10.0.2.2:8000');

class ApiClient {
  final Dio _dio;
  final _storage = const FlutterSecureStorage();
  String? _token;

  ApiClient() : _dio = Dio(BaseOptions(baseUrl: apiBase)) {
    _dio.interceptors.add(InterceptorsWrapper(onRequest: (o, h) {
      if (_token != null) o.headers['Authorization'] = 'Bearer $_token';
      h.next(o);
    }));
  }

  String get token => _token ?? '';
  Map<String, String> get authHeaders => {'Authorization': 'Bearer $_token'};
  String absoluteUrl(String path) => '$apiBase$path';

  Future<String?> loadToken() async =>
      _token = await _storage.read(key: 'jwt');

  Future<void> _saveToken(String t) async {
    _token = t;
    await _storage.write(key: 'jwt', value: t);
  }

  Future<void> clearToken() async {
    _token = null;
    await _storage.delete(key: 'jwt');
  }

  Future<User> signup(String email, String pw, String nickname) async {
    final r = await _dio.post('/auth/signup', data: {
      'email': email, 'password': pw, 'nickname': nickname});
    await _saveToken(r.data['token']);
    return User.fromJson(r.data['user']);
  }

  Future<User> login(String email, String pw) async {
    final r = await _dio.post('/auth/login',
        data: {'email': email, 'password': pw});
    await _saveToken(r.data['token']);
    return User.fromJson(r.data['user']);
  }

  Future<User> me() async => User.fromJson((await _dio.get('/me')).data);

  Future<AppSettings> getSettings() async =>
      AppSettings.fromJson((await _dio.get('/me/settings')).data);

  Future<AppSettings> putSettings(AppSettings s) async => AppSettings.fromJson(
      (await _dio.put('/me/settings', data: s.toJson())).data);

  Future<(List<FeedVideo>, int?)> feed({int? cursor, int limit = 10}) async {
    final r = await _dio.get('/feed', queryParameters: {
      if (cursor != null) 'cursor': cursor, 'limit': limit});
    final vids = (r.data['videos'] as List)
        .map((e) => FeedVideo.fromJson(e)).toList();
    return (vids, r.data['next_cursor'] as int?);
  }

  Future<(int, bool)> like(int id) async {
    final r = await _dio.post('/videos/$id/like');
    return (r.data['like_count'] as int, r.data['liked'] as bool);
  }

  Future<(int, bool)> unlike(int id) async {
    final r = await _dio.delete('/videos/$id/like');
    return (r.data['like_count'] as int, r.data['liked'] as bool);
  }

  Future<Exposure> sendEvent(int id, double watchedS, String variant) async {
    final r = await _dio.post('/videos/$id/events',
        data: {'watched_s': watchedS, 'variant': variant});
    return Exposure.fromJson(r.data);
  }

  Future<DashboardToday> dashboardToday() async =>
      DashboardToday.fromJson((await _dio.get('/dashboard/today')).data);

  Future<Weekly> dashboardWeekly() async =>
      Weekly.fromJson((await _dio.get('/dashboard/weekly')).data);

  Future<List<MyVideo>> myVideos() async =>
      ((await _dio.get('/me/videos')).data['videos'] as List)
          .map((e) => MyVideo.fromJson(e)).toList();

  Future<int> upload(String path, String title,
      {void Function(int, int)? onProgress}) async {
    final form = FormData.fromMap({
      'title': title,
      'file': await MultipartFile.fromFile(path),
    });
    final r = await _dio.post('/videos', data: form,
        onSendProgress: onProgress);
    return r.data['video_id'];
  }
}

final apiProvider = Provider<ApiClient>((ref) => ApiClient());
```

- [ ] **Step 2: 분석 통과 확인 후 커밋**

Run: `cd app && flutter analyze` → 경고 0
```bash
git add app/
git commit -m "API 클라이언트 — dio·토큰 인터셉터·전 엔드포인트"
```

---

### Task F4: 인증 상태 + 로그인 화면 + 셸

**Files:**
- Create: `app/lib/state/auth.dart`, `app/lib/screens/login.dart`, `app/lib/screens/shell.dart`
- Modify: `app/lib/main.dart`

**Interfaces:**
- Consumes: `apiProvider`
- Produces: `authProvider = AsyncNotifierProvider<AuthController, User?>` — `login/signup/logout` 메서드, 앱 시작 시 저장 토큰으로 `/me` 복원 / `LoginScreen` / `ShellScreen(body 3개: 피드·업로드·내페이지, 탭바 5개 중 shorts·구독은 SnackBar "준비 중")`

- [ ] **Step 1: auth.dart**

`app/lib/state/auth.dart`:
```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';

class AuthController extends AsyncNotifier<User?> {
  @override
  Future<User?> build() async {
    final api = ref.read(apiProvider);
    final t = await api.loadToken();
    if (t == null) return null;
    try {
      return await api.me();
    } catch (_) {
      await api.clearToken();
      return null;
    }
  }

  Future<void> login(String email, String pw) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(
        () => ref.read(apiProvider).login(email, pw));
  }

  Future<void> signup(String email, String pw, String nickname) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(
        () => ref.read(apiProvider).signup(email, pw, nickname));
  }

  Future<void> logout() async {
    await ref.read(apiProvider).clearToken();
    state = const AsyncData(null);
  }
}

final authProvider = AsyncNotifierProvider<AuthController, User?>(
    AuthController.new);
```

- [ ] **Step 2: login.dart**

`app/lib/screens/login.dart`:
```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/auth.dart';
import '../theme.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});
  @override
  ConsumerState<LoginScreen> createState() => _LoginState();
}

class _LoginState extends ConsumerState<LoginScreen> {
  final _email = TextEditingController();
  final _pw = TextEditingController();
  final _nick = TextEditingController();
  bool _signup = false;

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    return Scaffold(
      body: Center(child: SingleChildScrollView(
        padding: const EdgeInsets.all(32),
        child: Column(children: [
          const Text('검출기', style: TextStyle(
              fontSize: 32, fontWeight: FontWeight.bold)),
          const Text('광과민성 안전 숏폼 플랫폼',
              style: TextStyle(color: AppColors.sub)),
          const SizedBox(height: 32),
          TextField(controller: _email, decoration:
              const InputDecoration(labelText: '이메일')),
          TextField(controller: _pw, obscureText: true,
              decoration: const InputDecoration(labelText: '비밀번호 (8자+)')),
          if (_signup)
            TextField(controller: _nick, decoration:
                const InputDecoration(labelText: '닉네임')),
          const SizedBox(height: 24),
          if (auth.hasError)
            Padding(padding: const EdgeInsets.only(bottom: 8),
                child: Text('실패: 이메일/비밀번호를 확인하세요',
                    style: const TextStyle(color: AppColors.red))),
          FilledButton(
            onPressed: auth.isLoading ? null : () {
              final n = ref.read(authProvider.notifier);
              _signup
                  ? n.signup(_email.text.trim(), _pw.text, _nick.text.trim())
                  : n.login(_email.text.trim(), _pw.text);
            },
            child: Text(_signup ? '가입하기' : '로그인')),
          TextButton(
            onPressed: () => setState(() => _signup = !_signup),
            child: Text(_signup ? '로그인으로' : '계정이 없나요? 가입')),
        ]),
      )),
    );
  }
}
```

- [ ] **Step 3: shell.dart + main.dart 게이트**

`app/lib/screens/shell.dart` (피드·업로드·내페이지는 F6/F9 전까지 자리표시 위젯):
```dart
import 'package:flutter/material.dart';

import 'feed.dart';
import 'mypage.dart';
import 'upload.dart';

class ShellScreen extends StatefulWidget {
  const ShellScreen({super.key});
  @override
  State<ShellScreen> createState() => _ShellState();
}

class _ShellState extends State<ShellScreen> {
  int _idx = 0; // 0 피드, 1 업로드, 2 내페이지

  void _dummy() => ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('준비 중입니다')));

  @override
  Widget build(BuildContext context) {
    final body = switch (_idx) {
      1 => const UploadScreen(),
      2 => const MyPageScreen(),
      _ => const FeedScreen(),
    };
    return Scaffold(
      body: body,
      bottomNavigationBar: BottomAppBar(height: 56, child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: [
          IconButton(icon: const Icon(Icons.home_filled),
              onPressed: () => setState(() => _idx = 0)),
          IconButton(icon: const Icon(Icons.play_circle_outline),
              onPressed: _dummy),                       // shorts (더미)
          IconButton(icon: const Icon(Icons.add_box_outlined),
              onPressed: () => setState(() => _idx = 1)),
          IconButton(icon: const Icon(Icons.subscriptions_outlined),
              onPressed: _dummy),                       // 구독 (더미)
          IconButton(icon: const Icon(Icons.person_outline),
              onPressed: () => setState(() => _idx = 2)),
        ])),
    );
  }
}
```

이 태스크에서는 `feed.dart`/`upload.dart`/`mypage.dart`를 자리표시로 생성:
```dart
// app/lib/screens/feed.dart (F6 에서 교체)
import 'package:flutter/material.dart';
class FeedScreen extends StatelessWidget {
  const FeedScreen({super.key});
  @override
  Widget build(BuildContext c) => const Center(child: Text('피드'));
}
```
(`upload.dart`→`UploadScreen`·'업로드', `mypage.dart`→`MyPageScreen`·'내 페이지' 동일 형태.)

`app/lib/main.dart`의 `App.build` 를 게이트로 교체:
```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'screens/login.dart';
import 'screens/shell.dart';
import 'state/auth.dart';
import 'theme.dart';

class App extends ConsumerWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    return MaterialApp(
      title: '검출기', theme: appTheme,
      home: auth.when(
        data: (u) => u == null ? const LoginScreen() : const ShellScreen(),
        loading: () => const Scaffold(
            body: Center(child: CircularProgressIndicator())),
        error: (_, __) => const LoginScreen()));
  }
}
```

- [ ] **Step 4: 기기에서 확인 후 커밋**

Run: `cd app && flutter analyze && flutter run` (서버 compose 기동 상태) — 가입 → 셸 진입 확인.
```bash
git add app/
git commit -m "인증 상태·로그인 화면·탭 셸 — JWT 복원 게이트"
```

---

### Task F5: 설정 상태 + 설정 바텀시트

**Files:**
- Create: `app/lib/state/settings.dart`, `app/lib/widgets/settings_sheet.dart`

**Interfaces:**
- Consumes: `apiProvider`
- Produces: `settingsProvider = AsyncNotifierProvider<SettingsController, AppSettings>` — `setFilter(bool)`, `setAutoSkip(bool)` (서버 PUT 후 상태 갱신) / `showSettingsSheet(BuildContext, WidgetRef)` — 목업 ②: 토글 2개 + "광 노출 대시보드 확인" 행 (탭 → DashboardScreen push)

- [ ] **Step 1: settings.dart**

`app/lib/state/settings.dart`:
```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';

class SettingsController extends AsyncNotifier<AppSettings> {
  @override
  Future<AppSettings> build() => ref.read(apiProvider).getSettings();

  Future<void> setFilter(bool on) => _put(
      (s) => s.copyWith(filterOn: on));

  Future<void> setAutoSkip(bool on) => _put(
      (s) => s.copyWith(autoSkip: on));

  Future<void> _put(AppSettings Function(AppSettings) f) async {
    final cur = state.value ??
        const AppSettings(filterOn: true, autoSkip: false);
    state = AsyncData(await ref.read(apiProvider).putSettings(f(cur)));
  }
}

final settingsProvider =
    AsyncNotifierProvider<SettingsController, AppSettings>(
        SettingsController.new);
```

- [ ] **Step 2: settings_sheet.dart**

`app/lib/widgets/settings_sheet.dart`:
```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../screens/dashboard.dart';
import '../state/settings.dart';
import '../theme.dart';

void showSettingsSheet(BuildContext context) {
  showModalBottomSheet(
    context: context, backgroundColor: AppColors.card,
    builder: (_) => Consumer(builder: (context, ref, __) {
      final s = ref.watch(settingsProvider).value;
      if (s == null) return const SizedBox(height: 180);
      final n = ref.read(settingsProvider.notifier);
      return SafeArea(child: Column(mainAxisSize: MainAxisSize.min, children: [
        SwitchListTile(title: const Text('필터 기능 켜기'),
            value: s.filterOn, onChanged: n.setFilter),
        SwitchListTile(title: const Text('위험 영상 자동 스킵 켜기'),
            value: s.autoSkip, onChanged: n.setAutoSkip),
        ListTile(leading: const Icon(Icons.insights),
            title: const Text('광 노출 대시보드 확인'),
            onTap: () {
              Navigator.pop(context);
              Navigator.push(context, MaterialPageRoute(
                  builder: (_) => const DashboardScreen()));
            }),
      ]));
    }));
}
```

`app/lib/screens/dashboard.dart` 자리표시 생성 (F8 에서 교체):
```dart
import 'package:flutter/material.dart';
class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});
  @override
  Widget build(BuildContext c) => Scaffold(
      appBar: AppBar(title: const Text('광 노출 대시보드')),
      body: const Center(child: Text('대시보드')));
}
```

- [ ] **Step 3: 확인 후 커밋**

Run: `cd app && flutter analyze` → 경고 0
```bash
git add app/
git commit -m "설정 상태·바텀시트 — 필터·자동스킵 서버 동기화"
```

---

### Task F6: 피드 화면 — 세로 PageView·재생·좋아요·이벤트

**Files:**
- Create: `app/lib/state/feed.dart`, `app/lib/state/exposure.dart`, `app/lib/widgets/video_page.dart`, `app/lib/widgets/action_rail.dart`
- Modify: `app/lib/screens/feed.dart` (자리표시 교체)

**Interfaces:**
- Consumes: `apiProvider`, `settingsProvider`, `models.dart`
- Produces: `feedProvider = AsyncNotifierProvider<FeedController, List<FeedVideo>>` — `loadMore()`, `refreshAll()`, `toggleLike(int id)` / `exposureProvider = NotifierProvider<ExposureController, Exposure?>` — `update(Exposure)` (이벤트 응답 반영; F7 배너와 F8 이 구독) / `FeedScreen` — 스와이프 시 직전 영상 이벤트 전송, 우상단 필터 버튼(설정 시트), 설정 변경 시 refreshAll

- [ ] **Step 1: feed.dart (상태) + exposure.dart**

`app/lib/state/exposure.dart`:
```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/models.dart';

class ExposureController extends Notifier<Exposure?> {
  @override
  Exposure? build() => null;
  void update(Exposure e) => state = e;
}

final exposureProvider =
    NotifierProvider<ExposureController, Exposure?>(ExposureController.new);
```

`app/lib/state/feed.dart`:
```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';

class FeedController extends AsyncNotifier<List<FeedVideo>> {
  int? _cursor;
  bool _end = false, _loading = false;

  @override
  Future<List<FeedVideo>> build() async {
    _cursor = null; _end = false;
    final (vids, next) = await ref.read(apiProvider).feed();
    _cursor = next; _end = next == null || vids.isEmpty;
    return vids;
  }

  Future<void> loadMore() async {
    if (_end || _loading) return;
    _loading = true;
    try {
      final (vids, next) =
          await ref.read(apiProvider).feed(cursor: _cursor);
      _cursor = next; _end = next == null || vids.isEmpty;
      state = AsyncData([...state.value ?? [], ...vids]);
    } finally {
      _loading = false;
    }
  }

  Future<void> refreshAll() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(build);
  }

  Future<void> toggleLike(int id) async {
    final list = state.value;
    if (list == null) return;
    final i = list.indexWhere((v) => v.id == id);
    if (i < 0) return;
    final api = ref.read(apiProvider);
    final (count, liked) = list[i].likedByMe
        ? await api.unlike(id) : await api.like(id);
    final copy = [...list];
    copy[i] = list[i].copyWith(likeCount: count, likedByMe: liked);
    state = AsyncData(copy);
  }
}

final feedProvider =
    AsyncNotifierProvider<FeedController, List<FeedVideo>>(FeedController.new);
```

- [ ] **Step 2: video_page.dart — 재생 위젯**

`app/lib/widgets/video_page.dart`:
```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../theme.dart';
import 'action_rail.dart';

class VideoPage extends ConsumerStatefulWidget {
  final FeedVideo video;
  final bool active; // 현재 페이지일 때만 재생
  const VideoPage({super.key, required this.video, required this.active});
  @override
  ConsumerState<VideoPage> createState() => _VideoPageState();
}

class _VideoPageState extends ConsumerState<VideoPage> {
  VideoPlayerController? _c;
  bool _error = false;

  @override
  void initState() {
    super.initState();
    final api = ref.read(apiProvider);
    _c = VideoPlayerController.networkUrl(
        Uri.parse(api.absoluteUrl(widget.video.streamUrl)),
        httpHeaders: api.authHeaders)
      ..setLooping(true)
      ..initialize().then((_) {
        if (mounted) setState(() {});
        if (widget.active) _c!.play();
      }).catchError((_) {
        if (mounted) setState(() => _error = true);
      });
  }

  @override
  void didUpdateWidget(VideoPage old) {
    super.didUpdateWidget(old);
    if (widget.active && !old.active) _c?.play();
    if (!widget.active && old.active) _c?.pause();
  }

  @override
  void dispose() {
    _c?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final v = widget.video;
    return Stack(fit: StackFit.expand, children: [
      if (_error)
        const Center(child: Text('재생 실패 — 스와이프해서 다음 영상으로',
            style: TextStyle(color: AppColors.sub)))
      else if (_c != null && _c!.value.isInitialized)
        FittedBox(fit: BoxFit.cover, clipBehavior: Clip.hardEdge,
            child: SizedBox(width: _c!.value.size.width,
                height: _c!.value.size.height, child: VideoPlayer(_c!)))
      else
        const Center(child: CircularProgressIndicator()),
      // 하단 정보
      Positioned(left: 16, right: 88, bottom: 24, child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('@${v.uploaderNickname}',
              style: const TextStyle(fontWeight: FontWeight.bold)),
          Text(v.title, maxLines: 2, overflow: TextOverflow.ellipsis),
          if (v.risk != 'safe')
            Container(
              margin: const EdgeInsets.only(top: 6),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                  color: v.variant == 'filtered'
                      ? AppColors.blue.withValues(alpha: .25)
                      : AppColors.amber.withValues(alpha: .25),
                  borderRadius: BorderRadius.circular(6)),
              child: Text(v.variant == 'filtered'
                  ? '보호 필터 적용됨' : '⚠ 광 자극 원본',
                  style: const TextStyle(fontSize: 12))),
        ])),
      Positioned(right: 8, bottom: 24, child: ActionRail(video: v)),
    ]);
  }
}
```

- [ ] **Step 3: action_rail.dart**

`app/lib/widgets/action_rail.dart`:
```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/models.dart';
import '../state/feed.dart';
import '../theme.dart';

class ActionRail extends ConsumerWidget {
  final FeedVideo video;
  const ActionRail({super.key, required this.video});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    void dummy() => ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('준비 중입니다')));
    Widget item(IconData ic, String label, VoidCallback onTap,
            {Color? color}) =>
        Padding(padding: const EdgeInsets.only(bottom: 16), child: Column(
          children: [
            IconButton(icon: Icon(ic, size: 30, color: color), onPressed: onTap),
            Text(label, style: const TextStyle(fontSize: 12)),
          ]));
    return Column(mainAxisSize: MainAxisSize.min, children: [
      item(video.likedByMe ? Icons.favorite : Icons.favorite_border,
          '${video.likeCount}',
          () => ref.read(feedProvider.notifier).toggleLike(video.id),
          color: video.likedByMe ? AppColors.red : null),
      item(Icons.mode_comment_outlined, '댓글', dummy),
      item(Icons.share_outlined, '공유', dummy),
      item(Icons.autorenew, '리믹스', dummy),
    ]);
  }
}
```

- [ ] **Step 4: feed.dart (화면) 교체 — 이벤트 전송 포함**

`app/lib/screens/feed.dart`:
```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../state/exposure.dart';
import '../state/feed.dart';
import '../state/settings.dart';
import '../theme.dart';
import '../widgets/settings_sheet.dart';
import '../widgets/video_page.dart';

class FeedScreen extends ConsumerStatefulWidget {
  const FeedScreen({super.key});
  @override
  ConsumerState<FeedScreen> createState() => _FeedState();
}

class _FeedState extends ConsumerState<FeedScreen> {
  final _page = PageController();
  final _watch = Stopwatch();
  int _current = 0;

  @override
  void initState() {
    super.initState();
    _watch.start();
  }

  void _sendEvent(FeedVideo v) {
    final s = _watch.elapsed.inMilliseconds / 1000.0;
    _watch..reset()..start();
    if (s < 0.5) return; // 스쳐 지나간 페이지는 무시
    ref.read(apiProvider)
        .sendEvent(v.id, s.clamp(0, 600), v.variant)
        .then((e) => ref.read(exposureProvider.notifier).update(e))
        .catchError((_) {});
  }

  @override
  void deactivate() {
    final vids = ref.read(feedProvider).value;
    if (vids != null && _current < vids.length) _sendEvent(vids[_current]);
    super.deactivate();
  }

  @override
  Widget build(BuildContext context) {
    // 설정이 바뀌면 노출 규칙이 달라지므로 피드 재로드
    ref.listen(settingsProvider, (prev, next) {
      if (prev?.value != null && next.value != null &&
          (prev!.value!.filterOn != next.value!.filterOn ||
           prev.value!.autoSkip != next.value!.autoSkip)) {
        ref.read(feedProvider.notifier).refreshAll();
      }
    });
    final feed = ref.watch(feedProvider);
    return Stack(children: [
      feed.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Column(
            mainAxisSize: MainAxisSize.min, children: [
          const Text('피드를 불러오지 못했습니다'),
          TextButton(
              onPressed: () => ref.read(feedProvider.notifier).refreshAll(),
              child: const Text('다시 시도')),
        ])),
        data: (vids) => vids.isEmpty
            ? const Center(child: Text('아직 영상이 없습니다',
                style: TextStyle(color: AppColors.sub)))
            : PageView.builder(
                controller: _page, scrollDirection: Axis.vertical,
                itemCount: vids.length,
                onPageChanged: (i) {
                  _sendEvent(vids[_current]);
                  setState(() => _current = i);
                  if (i >= vids.length - 2) {
                    ref.read(feedProvider.notifier).loadMore();
                  }
                },
                itemBuilder: (_, i) => VideoPage(
                    key: ValueKey('${vids[i].id}-${vids[i].variant}'),
                    video: vids[i], active: i == _current))),
      // 우상단 필터 버튼 (목업 ①)
      Positioned(top: 48, right: 12, child: IconButton(
          icon: const Icon(Icons.filter_alt_outlined, size: 28),
          onPressed: () => showSettingsSheet(context))),
    ]);
  }
}
```

- [ ] **Step 5: 기기 확인 후 커밋**

Run: `cd app && flutter analyze && flutter run` — 서버에 영상 1개 이상 업로드해 둔 상태에서 피드 재생·스와이프·좋아요·토글 후 variant 교체 확인.
```bash
git add app/
git commit -m "피드 — 세로 PageView 재생·좋아요·시청 이벤트·설정 연동"
```

---

### Task F7: 경고 배너

**Files:**
- Create: `app/lib/widgets/warning_banner.dart`
- Modify: `app/lib/screens/feed.dart` (Stack 에 배너 추가)

**Interfaces:**
- Consumes: `exposureProvider`, `settingsProvider`, `shouldShowBanner`, `DashboardScreen`
- Produces: `WarningBanner` — 목업 ④: 앰버 배너 "경고! 위험 영상에 대한 노출이 많습니다. 필터 기능을 키는 것을 추천드립니다." + [필터 ON]·[대시보드 확인]

- [ ] **Step 1: warning_banner.dart**

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../logic/banner.dart';
import '../screens/dashboard.dart';
import '../state/exposure.dart';
import '../state/settings.dart';
import '../theme.dart';

class WarningBanner extends ConsumerWidget {
  const WarningBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final exposure = ref.watch(exposureProvider);
    final settings = ref.watch(settingsProvider).value;
    if (settings == null ||
        !shouldShowBanner(percent: exposure?.percent,
            filterOn: settings.filterOn)) {
      return const SizedBox.shrink();
    }
    return Positioned(top: 90, left: 12, right: 12, child: Material(
      color: AppColors.card, borderRadius: BorderRadius.circular(12),
      child: Padding(padding: const EdgeInsets.all(12), child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: const [
            Icon(Icons.warning_amber, color: AppColors.amber),
            SizedBox(width: 8),
            Expanded(child: Text('경고! 위험 영상에 대한 노출이 많습니다.\n'
                '필터 기능을 키는 것을 추천드립니다.',
                style: TextStyle(fontSize: 13))),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: AppColors.amber,
                    foregroundColor: Colors.black),
                onPressed: () =>
                    ref.read(settingsProvider.notifier).setFilter(true),
                child: const Text('필터 ON')),
            const SizedBox(width: 8),
            OutlinedButton(
                onPressed: () => Navigator.push(context, MaterialPageRoute(
                    builder: (_) => const DashboardScreen())),
                child: const Text('대시보드 확인')),
          ]),
        ]))));
  }
}
```

- [ ] **Step 2: FeedScreen Stack 마지막에 `const WarningBanner()` 추가**

- [ ] **Step 3: 확인 후 커밋**

수동 확인: 서버 `.env`의 `DAILY_BUDGET_S=30`으로 낮추고 재기동 → 위험 원본 시청 반복 → 배너 표시 → [필터 ON] → 배너 사라짐 + 피드 재로드.
```bash
git add app/
git commit -m "노출 경고 배너 — 임계 초과 시 필터 ON 유도"
```

---

### Task F8: 대시보드 화면

**Files:**
- Modify: `app/lib/screens/dashboard.dart` (자리표시 교체)

**Interfaces:**
- Consumes: `apiProvider` (dashboardToday/dashboardWeekly), `settingsProvider`, `exposureProvider`, fl_chart
- Produces: 목업 ③ 화면 — 상태 카드 / 누적 라인차트(80% 기준선) / 주간 바차트 / 자극 유형 4행 / [필터 켜기]

- [ ] **Step 1: 구현**

`app/lib/screens/dashboard.dart` 전체 교체:
```dart
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../state/settings.dart';
import '../theme.dart';

const _statusKo = {'good': '양호', 'caution': '주의', 'warning': '경고'};
const _statusColor = {
  'good': Colors.greenAccent, 'caution': AppColors.amber,
  'warning': AppColors.red};
const _stimKo = [
  ('flash', '고휘도 플래시', AppColors.amber),
  ('red', '포화 적색', AppColors.red),
  ('pattern', '정적 패턴', Colors.cyanAccent),
  ('cut', '화면 전환', Color(0xFF8A7BFF)),
];

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.read(apiProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('광 노출 대시보드')),
      body: FutureBuilder(
        future: Future.wait([api.dashboardToday(), api.dashboardWeekly()]),
        builder: (context, snap) {
          if (snap.hasError) {
            return const Center(child: Text('불러오기 실패'));
          }
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final today = snap.data![0] as DashboardToday;
          final weekly = snap.data![1] as Weekly;
          final min = (today.exposureS ~/ 60);
          final sec = (today.exposureS % 60).round();
          return ListView(padding: const EdgeInsets.all(16), children: [
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('오늘의 광 자극 노출',
                  style: TextStyle(color: AppColors.sub)),
              Row(children: [
                Icon(Icons.warning_amber,
                    color: _statusColor[today.status]),
                const SizedBox(width: 6),
                Text(_statusKo[today.status] ?? today.status,
                    style: TextStyle(fontSize: 22,
                        fontWeight: FontWeight.bold,
                        color: _statusColor[today.status])),
              ]),
              const SizedBox(height: 6),
              Text('오늘 위험 영상 ${today.riskyViews}회 · '
                  '위험 노출 시간 $min분 $sec초'),
              Text('일간 임계치(80%) 대비 누적 ${today.percent}%',
                  style: const TextStyle(color: AppColors.sub)),
            ])),
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('광 자극 노출도'),
              const SizedBox(height: 12),
              SizedBox(height: 160, child: _curveChart(today)),
            ])),
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('위험 영상 노출 수 (주간)'),
              Text('오늘 ${today.riskyViews}회 · 주간 평균 ${weekly.avg}회',
                  style: const TextStyle(
                      color: AppColors.sub, fontSize: 12)),
              const SizedBox(height: 12),
              SizedBox(height: 140, child: _weekChart(weekly)),
            ])),
            _card(Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
              const Text('오늘 노출된 자극'),
              const SizedBox(height: 8),
              for (final (key, label, color) in _stimKo)
                Padding(padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(children: [
                  SizedBox(width: 110, child: Text(label,
                      style: const TextStyle(fontSize: 13))),
                  Expanded(child: LinearProgressIndicator(
                      value: ((today.stimulus[key] ?? 0) / 10).clamp(0, 1),
                      color: color,
                      backgroundColor: AppColors.bg, minHeight: 6)),
                  SizedBox(width: 44, child: Text(
                      '  ${today.stimulus[key] ?? 0}회',
                      style: const TextStyle(fontSize: 13))),
                ])),
            ])),
            const SizedBox(height: 8),
            FilledButton(
                onPressed: () {
                  ref.read(settingsProvider.notifier).setFilter(true);
                  Navigator.pop(context);
                },
                child: const Text('필터 켜기')),
          ]);
        }),
    );
  }

  Widget _card(Widget child) => Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: AppColors.card,
          borderRadius: BorderRadius.circular(16)),
      child: child);

  Widget _curveChart(DashboardToday t) {
    final spots = [
      const FlSpot(0, 0),
      ...t.curve.map((c) => FlSpot(c.hour.toDouble(), c.percent)),
    ];
    return LineChart(LineChartData(
      minX: 0, maxX: 24, minY: 0,
      maxY: [100.0, t.percent + 10].reduce((a, b) => a > b ? a : b),
      titlesData: const FlTitlesData(
          leftTitles: AxisTitles(sideTitles: SideTitles(
              showTitles: true, reservedSize: 36)),
          bottomTitles: AxisTitles(sideTitles: SideTitles(
              showTitles: true, interval: 6)),
          topTitles: AxisTitles(), rightTitles: AxisTitles()),
      extraLinesData: ExtraLinesData(horizontalLines: [
        HorizontalLine(y: 80, color: AppColors.red, strokeWidth: 1,
            dashArray: [6, 4]),
      ]),
      lineBarsData: [LineChartBarData(
          spots: spots, color: AppColors.red, isCurved: false,
          belowBarData: BarAreaData(show: true,
              color: AppColors.red.withValues(alpha: .15)))],
    ));
  }

  Widget _weekChart(Weekly w) {
    const days = ['월', '화', '수', '목', '금', '토', '일'];
    return BarChart(BarChartData(
      titlesData: FlTitlesData(
          bottomTitles: AxisTitles(sideTitles: SideTitles(
              showTitles: true,
              getTitlesWidget: (v, _) {
                final d = DateTime.parse(w.days[v.toInt()].date);
                return Text(days[d.weekday - 1],
                    style: const TextStyle(fontSize: 11));
              })),
          leftTitles: const AxisTitles(),
          topTitles: const AxisTitles(), rightTitles: const AxisTitles()),
      barGroups: [
        for (var i = 0; i < w.days.length; i++)
          BarChartGroupData(x: i, barRods: [BarChartRodData(
              toY: w.days[i].riskyViews.toDouble(),
              color: i == w.days.length - 1
                  ? AppColors.blue : AppColors.blue.withValues(alpha: .4),
              width: 16,
              borderRadius: BorderRadius.circular(4))]),
      ],
    ));
  }
}
```

- [ ] **Step 2: 확인 후 커밋**

Run: `cd app && flutter analyze && flutter run` — 이벤트 몇 건 쌓은 뒤 대시보드 수치·차트 확인.
```bash
git add app/
git commit -m "광 노출 대시보드 화면 — 상태·누적 곡선·주간·자극 유형"
```

---

### Task F9: 업로드 + 내 페이지

**Files:**
- Modify: `app/lib/screens/upload.dart`, `app/lib/screens/mypage.dart` (자리표시 교체)

**Interfaces:**
- Consumes: `apiProvider`, `authProvider`, image_picker
- Produces: 업로드 화면(선택→제목→진행률→완료 안내), 내 페이지(내 영상+상태 뱃지+로그아웃)

- [ ] **Step 1: upload.dart 교체**

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../api/client.dart';
import '../theme.dart';

class UploadScreen extends ConsumerStatefulWidget {
  const UploadScreen({super.key});
  @override
  ConsumerState<UploadScreen> createState() => _UploadState();
}

class _UploadState extends ConsumerState<UploadScreen> {
  final _title = TextEditingController();
  XFile? _file;
  double? _progress;
  String? _message;

  Future<void> _pick() async {
    final f = await ImagePicker().pickVideo(source: ImageSource.gallery);
    if (f != null) setState(() { _file = f; _message = null; });
  }

  Future<void> _upload() async {
    if (_file == null) return;
    setState(() { _progress = 0; _message = null; });
    try {
      await ref.read(apiProvider).upload(_file!.path, _title.text,
          onProgress: (sent, total) =>
              setState(() => _progress = sent / total));
      setState(() {
        _progress = null; _file = null; _title.clear();
        _message = '업로드 완료 — 검출·보정 처리 중입니다.\n'
            '완료되면 피드와 내 페이지에 표시됩니다.';
      });
    } catch (e) {
      setState(() {
        _progress = null;
        _message = '업로드 실패: 크기(200MB)·길이(3분) 제한을 확인하세요';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('영상 업로드')),
      body: Padding(padding: const EdgeInsets.all(16), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          OutlinedButton.icon(onPressed: _pick,
              icon: const Icon(Icons.video_library_outlined),
              label: Text(_file == null ? '갤러리에서 영상 선택' : '선택됨: 변경')),
          const SizedBox(height: 12),
          TextField(controller: _title,
              decoration: const InputDecoration(labelText: '제목')),
          const SizedBox(height: 20),
          if (_progress != null)
            LinearProgressIndicator(value: _progress)
          else
            FilledButton(onPressed: _file == null ? null : _upload,
                child: const Text('업로드')),
          if (_message != null)
            Padding(padding: const EdgeInsets.only(top: 16),
                child: Text(_message!,
                    style: const TextStyle(color: AppColors.sub))),
        ])),
    );
  }
}
```

- [ ] **Step 2: mypage.dart 교체**

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../state/auth.dart';
import '../theme.dart';

const _badge = {
  'processing': ('처리 중', AppColors.sub),
  'ready': ('게시됨', Colors.greenAccent),
  'failed': ('처리 실패', AppColors.red),
};

class MyPageScreen extends ConsumerWidget {
  const MyPageScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authProvider).value;
    return Scaffold(
      appBar: AppBar(title: Text('@${user?.nickname ?? ''}'), actions: [
        IconButton(icon: const Icon(Icons.logout),
            onPressed: () => ref.read(authProvider.notifier).logout()),
      ]),
      body: FutureBuilder(
        future: ref.read(apiProvider).myVideos(),
        builder: (context, snap) {
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final vids = snap.data as List<MyVideo>;
          if (vids.isEmpty) {
            return const Center(child: Text('업로드한 영상이 없습니다',
                style: TextStyle(color: AppColors.sub)));
          }
          return ListView.builder(itemCount: vids.length,
              itemBuilder: (_, i) {
            final v = vids[i];
            final (label, color) = _badge[v.status] ?? (v.status, AppColors.sub);
            final riskNote = v.status == 'ready' && v.risk == 'uncorrected'
                ? ' · 보정 미완(자동 스킵 대상)' : '';
            return ListTile(
              title: Text(v.title),
              subtitle: Text('조회 ${v.viewCount} · 좋아요 ${v.likeCount}$riskNote',
                  style: const TextStyle(fontSize: 12)),
              trailing: Text(label, style: TextStyle(color: color)));
          });
        }),
    );
  }
}
```

- [ ] **Step 3: 확인 후 커밋**

Run: `cd app && flutter analyze && flutter run` — 업로드 → 내 페이지 "처리 중" → 워커 완료 후 "게시됨" 확인.
```bash
git add app/
git commit -m "업로드 화면·내 페이지 — 진행률·처리 상태 뱃지"
```

---

### Task F10: E2E 수동 체크리스트

**Files:**
- Create: `docs/superpowers/plans/2026-08-20-e2e-checklist.md`

- [ ] **Step 1: 체크리스트 작성 후 실기기에서 전 항목 수행**

```markdown
# E2E 체크리스트 (실기기, 서버 compose 기동)
서버 준비: DAILY_BUDGET_S=60 으로 낮춰 재기동. make_testclips 01 클립을 mp4 로 변환해 폰에 저장.
- [ ] 가입 → 로그인 → 앱 재시작 시 자동 로그인
- [ ] 01_flash(위반) 영상 업로드 → 내 페이지 "처리 중" → 수 분 내 "게시됨"
- [ ] 안전 영상 업로드 → risk 뱃지 없음, 피드에서 원본 재생
- [ ] 필터 ON: 위반 영상이 "보호 필터 적용됨"으로 재생 (점멸 억제 확인)
- [ ] 필터 OFF: 같은 영상 "⚠ 광 자극 원본" + 시청 시 대시보드 수치 상승
- [ ] 반복 시청으로 80% 초과 → 경고 배너 → [필터 ON] → 배너 사라지고 보정본 재생
- [ ] 자동 스킵 ON → 위험 영상이 피드에서 사라짐
- [ ] 대시보드: 오늘 횟수·시간·%·곡선·주간·자극 유형 수치가 시청 내역과 일치
- [ ] 좋아요 토글·조회수 증가 확인
- [ ] 200MB/3분 초과·비영상 파일 업로드 → 오류 안내
- [ ] 기내모드에서 피드 → "다시 시도" 동작
```

- [ ] **Step 2: 전 항목 통과 후 커밋**

```bash
git add docs/
git commit -m "E2E 수동 체크리스트 — 전 항목 통과 기록"
```

---

## 완료 기준

- `flutter analyze` 경고 0, `flutter test` 전부 PASS
- E2E 체크리스트 전 항목 통과 (스펙 5절의 최종 E2E 기준 포함)
