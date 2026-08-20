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
