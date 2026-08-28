import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:image_picker/image_picker.dart';

import 'models.dart';

const _configuredApiBase = String.fromEnvironment(
  'API_BASE',
  defaultValue: 'http://10.0.2.2:8000',
);
final apiBase = kIsWeb && _configuredApiBase.isEmpty
    ? Uri.base.origin
    : _configuredApiBase;
const maxUploadMb = 500;
const maxUploadBytes = maxUploadMb * 1024 * 1024;

class ApiClient {
  final Dio _dio;
  final _storage = const FlutterSecureStorage();
  String? _token;
  String? _mediaToken;
  DateTime? _mediaTokenRefreshAt;
  Future<void>? _mediaTokenRefresh;
  Future<void> Function()? onUnauthorized;

  ApiClient()
    : _dio = Dio(
        BaseOptions(
          baseUrl: apiBase,
          connectTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 30),
        ),
      ) {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (o, h) {
          if (o.extra['publicAuth'] != true && _token != null) {
            o.headers['Authorization'] = 'Bearer $_token';
          }
          h.next(o);
        },
        onError: (e, h) async {
          final authenticated = e.requestOptions.headers.containsKey(
            'Authorization',
          );
          if (e.response?.statusCode == 401 &&
              authenticated &&
              e.requestOptions.extra['publicAuth'] != true) {
            await onUnauthorized?.call();
          }
          h.next(e);
        },
      ),
    );
  }

  String get token => _token ?? '';
  Map<String, String> get authHeaders => {'Authorization': 'Bearer $_token'};
  String absoluteUrl(String path) {
    var url = '$apiBase$path';
    // 웹의 <video>/<img>는 인증 헤더를 못 보내므로 API 권한이 없는
    // 단기 media token만 쿼리로 전달한다.
    if (kIsWeb && _mediaToken != null) {
      url += url.contains('?')
          ? '&token=${Uri.encodeQueryComponent(_mediaToken!)}'
          : '?token=${Uri.encodeQueryComponent(_mediaToken!)}';
    }
    return url;
  }

  Future<void> _refreshMediaToken({bool force = false}) async {
    if (!kIsWeb || _token == null) return;
    final now = DateTime.now();
    if (!force &&
        _mediaToken != null &&
        _mediaTokenRefreshAt != null &&
        now.isBefore(_mediaTokenRefreshAt!)) {
      return;
    }
    // 로그인 직후 Shell과 Feed가 동시에 build돼도 토큰 요청은 하나만 보낸다.
    final pending = _mediaTokenRefresh;
    if (pending != null) return pending;
    final refresh = () async {
      final r = await _dio.post('/auth/media-token');
      _mediaToken = r.data['token'] as String;
      final ttl = (r.data['expires_in'] as num?)?.toInt() ?? 3600;
      _mediaTokenRefreshAt = DateTime.now().add(
        Duration(seconds: (ttl * 0.8).round()),
      );
    }();
    _mediaTokenRefresh = refresh;
    try {
      await refresh;
    } finally {
      if (identical(_mediaTokenRefresh, refresh)) {
        _mediaTokenRefresh = null;
      }
    }
  }

  Future<String?> loadToken() async {
    _token = await _storage.read(key: 'jwt');
    // 미디어 토큰 발급 장애가 저장된 로그인 세션까지 무효화하지 않게 한다.
    if (_token != null) {
      try {
        await _refreshMediaToken(force: true);
      } catch (_) {
        /* feed 호출에서 다시 시도 */
      }
    }
    return _token;
  }

  Future<void> _saveToken(String t) async {
    _token = t;
    await _storage.write(key: 'jwt', value: t);
    // 액세스 토큰 저장이 성공했다면 로그인 자체는 성공이다. 웹 미디어용
    // 보조 토큰은 일시적 네트워크 실패 시 feed 호출에서 다시 받는다.
    try {
      await _refreshMediaToken(force: true);
    } catch (_) {
      /* feed 호출에서 다시 시도 */
    }
  }

  Future<void> clearToken() async {
    _token = null;
    _mediaToken = null;
    _mediaTokenRefreshAt = null;
    _mediaTokenRefresh = null;
    await _storage.delete(key: 'jwt');
  }

  Future<User> signup(String email, String pw, String nickname) async {
    final r = await _dio.post(
      '/auth/signup',
      data: {'email': email, 'password': pw, 'nickname': nickname},
      options: Options(extra: {'publicAuth': true}),
    );
    await _saveToken(r.data['token']);
    return User.fromJson(r.data['user']);
  }

  Future<User> login(String email, String pw) async {
    final r = await _dio.post(
      '/auth/login',
      data: {'email': email, 'password': pw},
      options: Options(extra: {'publicAuth': true}),
    );
    await _saveToken(r.data['token']);
    return User.fromJson(r.data['user']);
  }

  Future<User> me() async => User.fromJson((await _dio.get('/me')).data);

  Future<AppSettings> getSettings() async =>
      AppSettings.fromJson((await _dio.get('/me/settings')).data);

  Future<AppSettings> putSettings(AppSettings s) async => AppSettings.fromJson(
    (await _dio.put('/me/settings', data: s.toJson())).data,
  );

  Future<(List<FeedVideo>, int?)> feed({int? cursor, int limit = 10}) async {
    await _refreshMediaToken();
    final r = await _dio.get(
      '/feed',
      queryParameters: {'cursor': ?cursor, 'limit': limit},
    );
    final vids = (r.data['videos'] as List)
        .map((e) => FeedVideo.fromJson(e))
        .toList();
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
    final r = await _dio.post(
      '/videos/$id/events',
      data: {'watched_s': watchedS, 'variant': variant},
    );
    return Exposure.fromJson(r.data);
  }

  Future<DashboardToday> dashboardToday() async =>
      DashboardToday.fromJson((await _dio.get('/dashboard/today')).data);

  Future<Weekly> dashboardWeekly() async =>
      Weekly.fromJson((await _dio.get('/dashboard/weekly')).data);

  Future<List<RecentImpact>> fetchRecentImpact({int limit = 10}) async =>
      ((await _dio.get(
                '/dashboard/recent_impact',
                queryParameters: {'limit': limit},
              )).data['items']
              as List)
          .map((e) => RecentImpact.fromJson(e))
          .toList();

  Future<VideoReport> videoReport(int id) async =>
      VideoReport.fromJson((await _dio.get('/videos/$id/report')).data);

  Future<(double?, List<SegmentSpan>)> videoSegments(int id) async {
    final r = (await _dio.get('/videos/$id/segments')).data;
    return (
      (r['duration_s'] as num?)?.toDouble(),
      ((r['segments'] ?? []) as List)
          .map((e) => SegmentSpan.fromJson(e))
          .toList(),
    );
  }

  Future<List<MyVideo>> myVideos() async =>
      ((await _dio.get('/me/videos')).data['videos'] as List)
          .map((e) => MyVideo.fromJson(e))
          .toList();

  Future<AdminMetrics> adminMetrics({double cpm = 5000}) async =>
      AdminMetrics.fromJson(
        (await _dio.get('/admin/metrics', queryParameters: {'cpm': cpm})).data,
      );

  Future<int> upload(
    XFile file,
    String title, {
    void Function(int, int)? onProgress,
  }) async {
    final length = await file.length();
    if (length > maxUploadBytes) {
      throw ArgumentError('영상은 최대 ${maxUploadMb}MB까지 업로드할 수 있습니다.');
    }
    // 웹에서 readAsBytes()로 500MB 전체를 메모리에 복제하지 않고 스트림으로
    // 전송한다. 이전 방식은 대용량 파일에서 멈춤·브라우저 종료를 유발했다.
    final mf = kIsWeb
        ? MultipartFile.fromStream(
            () => file.openRead(),
            length,
            filename: file.name,
          )
        : await MultipartFile.fromFile(file.path, filename: file.name);
    final form = FormData.fromMap({'title': title, 'file': mf});
    final r = await _dio.post(
      '/videos',
      data: form,
      options: Options(sendTimeout: const Duration(minutes: 30)),
      onSendProgress: onProgress,
    );
    return r.data['video_id'];
  }
}

final apiProvider = Provider<ApiClient>((ref) => ApiClient());
