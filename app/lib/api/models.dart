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
  /// 보정본이 존재해 원본/필터본을 오갈 수 있는 영상인가.
  bool get canToggleVariant => risk == 'corrected';

  static String streamUrlFor(int id, String variant) =>
      '/videos/$id/stream?variant=$variant';

  FeedVideo copyWith({int? likeCount, bool? likedByMe, String? variant}) =>
      FeedVideo(
      id: id, title: title, uploaderNickname: uploaderNickname, risk: risk,
      variant: variant ?? this.variant,
      streamUrl: variant == null ? streamUrl : streamUrlFor(id, variant),
      thumbUrl: thumbUrl,
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
