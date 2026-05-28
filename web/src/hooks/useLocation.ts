import { useState, useCallback } from "react";
import type { LocationData } from "../api/types";
import { reverseGeocode } from "../api/client";
import { normalizeLocationText, inferCityFromLocation } from "../utils/location";

function coarseCoordinates(lat: number, lng: number) {
  return { lat: Math.round(lat * 100) / 100, lng: Math.round(lng * 100) / 100 };
}

export interface LocationStatus {
  message: string;
  state: "success" | "pending" | "error" | "manual";
}

export function useLocation() {
  const defaultCity = "北京";
  const [origin, setOrigin] = useState("北京 朝阳区 望京 SOHO");
  const [locationData, setLocationData] = useState<LocationData | null>(null);
  const [city, setCity] = useState(() => inferCityFromLocation("北京 朝阳区 望京 SOHO") || defaultCity);
  const [status, setStatus] = useState<LocationStatus>({
    message: "格式：城市 + 区/县 + 商圈/地标。可手动输入，也可定位后直接修改。",
    state: "manual",
  });
  const [locating, setLocating] = useState(false);

  const updateOrigin = useCallback(
    (value: string) => {
      setOrigin(value);
      if (locationData) {
        const editedAddress = normalizeLocationText(value);
        const editedCity = inferCityFromLocation(editedAddress);
        if (!editedAddress) {
          setLocationData(null);
          return;
        }
        if (editedCity && locationData.city && editedCity !== locationData.city) {
          setLocationData(null);
          setCity(editedCity);
          return;
        }
        setCity(editedCity || locationData.city || city || defaultCity);
        setLocationData({
          ...locationData,
          city: editedCity || locationData.city || city,
          formatted_address: editedAddress,
          home_location: editedAddress,
          address_confidence: "edited",
        });
        setStatus({ message: "已修改定位地址，将继续使用大概坐标计算距离和路线。", state: "success" });
      } else {
        const inferred = inferCityFromLocation(value);
        setCity(inferred || city || defaultCity);
      }
    },
    [locationData, city, defaultCity],
  );

  const locate = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setStatus({ message: "当前浏览器不支持定位，请手动输入出发地。", state: "error" });
      return;
    }

    setLocating(true);
    setStatus({ message: "正在请求浏览器定位授权...", state: "pending" });

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const coarse = coarseCoordinates(position.coords.latitude, position.coords.longitude);
        const loc: LocationData = {
          lat: coarse.lat,
          lng: coarse.lng,
          accuracy_m: Math.max(1000, Math.round(position.coords.accuracy || 0)),
          precision: "approximate",
          home_location: "我的大概位置",
        };
        setLocationData(loc);

        try {
          const address = await reverseGeocode({ lat: loc.lat, lng: loc.lng }, loc.precision);
          const formattedAddress =
            normalizeLocationText(address.formatted_address) ||
            normalizeLocationText(`${address.city || ""} ${address.district || ""} ${address.landmark || ""}`);
          const resolvedCity = normalizeLocationText(address.city) || inferCityFromLocation(formattedAddress) || city || defaultCity;

          setCity(resolvedCity);
          setOrigin(formattedAddress || "我的大概位置");
          setLocationData({
            ...loc,
            city: resolvedCity,
            district: normalizeLocationText(address.district),
            landmark: normalizeLocationText(address.landmark),
            formatted_address: formattedAddress,
            home_location: formattedAddress || "我的大概位置",
            address_source: address.source,
            address_confidence: address.confidence,
          });

          if (address.confidence === "low") {
            setStatus({
              message: "暂时只定位到大概区域，请在输入框补充城市、区县或商圈后再生成方案。",
              state: "pending",
            });
          } else {
            setStatus({
              message: `已填入地址：${formattedAddress || "我的大概位置"}。可直接修改；仅用于附近规划，不会发送精确坐标。`,
              state: "success",
            });
          }
        } catch {
          setOrigin("我的大概位置");
          setStatus({
            message: "已获取大概坐标，但地址反查失败；可手动补充城市、区县和商圈。",
            state: "pending",
          });
        } finally {
          setLocating(false);
        }
      },
      (error) => {
        setLocationData(null);
        const messages: Record<number, string> = {
          [error.PERMISSION_DENIED]: "定位授权被拒绝，将继续使用手动出发地。",
          [error.POSITION_UNAVAILABLE]: "暂时无法获取当前位置，请手动输入出发地。",
          [error.TIMEOUT]: "定位超时，请重试或手动输入出发地。",
        };
        setStatus({ message: messages[error.code] || "定位失败，请手动输入出发地。", state: "error" });
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  }, [city, defaultCity]);

  return { origin, updateOrigin, locationData, city, status, locating, locate };
}
