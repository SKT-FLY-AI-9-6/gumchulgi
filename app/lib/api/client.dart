import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:image_picker/image_picker.dart';

import 'models.dart';

const _configuredApiBase = String.fromEnvironment('API_BASE',
    defaultValue: 'http://10.0.2.2:8000');
final apiBase = kIsWeb && _configuredApiBase.isEmpty
    ? Uri.base.origin
    : _configuredApiBase;

class ApiClient {
  final Dio _dio;
  final _storage = const FlutterSecureStorage();
  String? _token;
  String? _mediaToken;
  DateTime? _mediaTokenRefreshAt;
  void Function()? onUnauthorized;

  ApiClient() : _dio = Dio(BaseOptions(baseUrl: apiBase)) {
    _dio.interceptors.add(InterceptorsWrapper(onRequest: (o, h) {
      if (_token != null) o.headers['Authorization'] = 'Bearer $_token';
      h.next(o);
    }, onError: (e, h) {
      if (e.response?.statusCode == 401) onUnauthorized?.call();
      h.next(e);
    }));
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
    if (!force && _mediaToken != null && _mediaTokenRefreshAt != null &&
        now.isBefore(_mediaTokenRefreshAt!)) return;
    final r = await _dio.post('/auth/media-token');
    _mediaToken = r.data['token'] as String;
    final ttl = (r.data['expires_in'] as num?)?.toInt() ?? 3600;
    _mediaTokenRefreshAt = now.add(Duration(seconds: (ttl * 0.8).round()));
  }

  Future<String?> loadToken() async {
    _token = await _storage.read(key: 'jwt');
    if (_token != null) await _refreshMediaToken(force: true);
    return _token;
  }

  Future<void> _saveToken(String t) async {
    _token = t;
    await _storage.write(key: 'jwt', value: t);
    await _refreshMediaToken(force: true);
  }

  Future<void> clearToken() async {
    _token = null;
    _mediaToken = null;
    _mediaTokenRefreshAt = null;
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
    await _refreshMediaToken();
    final r = await _dio.get('/feed', queryParameters: {
      'cursor': ?cursor, 'limit': limit});
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

  Future<List<RecentImpact>> fetchRecentImpact({int limit = 10}) async =>
      ((await _dio.get('/dashboard/recent_impact',
              queryParameters: {'limit': limit})).data['items'] as List)
          .map((e) => RecentImpact.fromJson(e)).toList();

  Future<VideoReport> videoReport(int id) async =>
      VideoReport.fromJson((await _dio.get('/videos/$id/report')).data);

  Future<(double?, List<SegmentSpan>)> videoSegments(int id) async {
    final r = (await _dio.get('/videos/$id/segments')).data;
    return ((r['duration_s'] as num?)?.toDouble(),
        ((r['segments'] ?? []) as List)
            .map((e) => SegmentSpan.fromJson(e)).toList());
  }

  Future<List<MyVideo>> myVideos() async =>
      ((await _dio.get('/me/videos')).data['videos'] as List)
          .map((e) => MyVideo.fromJson(e)).toList();

  Future<AdminMetrics> adminMetrics({double cpm = 5000}) async =>
      AdminMetrics.fromJson((await _dio.get('/admin/metrics',
          queryParameters: {'cpm': cpm})).data);

  Future<int> upload(XFile file, String title,
      {void Function(int, int)? onProgress}) async {
    // 웹은 파일 경로가 없어(blob) bytes 로 전송한다.
    final mf = kIsWeb
        ? MultipartFile.fromBytes(await file.readAsBytes(),
            filename: file.name)
        : await MultipartFile.fromFile(file.path);
    final form = FormData.fromMap({
      'title': title,
      'file': mf,
    });
    final r = await _dio.post('/videos', data: form,
        onSendProgress: onProgress);
    return r.data['video_id'];
  }
}

final apiProvider = Provider<ApiClient>((ref) => ApiClient());
