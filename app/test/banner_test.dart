import 'package:flutter_test/flutter_test.dart';
import 'package:gumchulgi_app/logic/banner.dart';

void main() {
  test('80% 이상 + 필터 OFF 에서만 배너', () {
    expect(shouldShowBanner(percent: 86, filterOn: false), true);
    expect(shouldShowBanner(percent: 86, filterOn: true), false);
    expect(shouldShowBanner(percent: 79.9, filterOn: false), false);
    expect(shouldShowBanner(percent: null, filterOn: false), false);
  });

  test('닫은 뒤에는 10%p 더 오르기 전까지 숨김', () {
    expect(shouldShowBanner(percent: 86, filterOn: false, dismissedAt: 86),
        false);
    expect(shouldShowBanner(percent: 95, filterOn: false, dismissedAt: 86),
        false);
    expect(shouldShowBanner(percent: 96, filterOn: false, dismissedAt: 86),
        true);
    // 필터를 켜면 닫기 여부와 무관하게 숨김
    expect(shouldShowBanner(percent: 99, filterOn: true, dismissedAt: 86),
        false);
  });
}
