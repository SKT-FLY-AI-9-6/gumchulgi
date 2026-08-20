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
