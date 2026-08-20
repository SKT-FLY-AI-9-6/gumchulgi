bool shouldShowBanner({required double? percent, required bool filterOn}) =>
    percent != null && percent >= 80 && !filterOn;
