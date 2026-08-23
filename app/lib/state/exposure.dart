import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/models.dart';

class ExposureController extends Notifier<Exposure?> {
  @override
  Exposure? build() => null;
  void update(Exposure e) => state = e;
}

final exposureProvider =
    NotifierProvider<ExposureController, Exposure?>(ExposureController.new);

/// 경고 배너를 닫은 시점의 노출 %. null 이면 닫은 적 없음.
class BannerDismissController extends Notifier<double?> {
  @override
  double? build() => null;
  void dismiss(double percent) => state = percent;
}

final bannerDismissProvider =
    NotifierProvider<BannerDismissController, double?>(
        BannerDismissController.new);
