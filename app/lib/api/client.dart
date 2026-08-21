import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:image_picker/image_picker.dart';

import 'models.dart';

const apiBase = String.fromEnvironment('API_BASE',
    defaultValue: 'http://10.0.2.2:8000');

class ApiClient {
  final Dio _dio;
  final _storage = const FlutterSecureStorage();
  String? _token;
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
    // 웹의 <video>/<img>는 인증 헤더를 못 보내므로 토큰을 쿼리로 전달
    // (서버는 운영 환경이 아닐 때만 허용).
    if (kIsWeb && _token != null) {
      url += url.contains('?') ? '&token=$_token' : '?token=$_token';
    }
    return url;
  }

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

  Future<List<MyVideo>> myVideos() async =>
      ((await _dio.get('/me/videos')).data['videos'] as List)
          .map((e) => MyVideo.fromJson(e)).toList();

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
