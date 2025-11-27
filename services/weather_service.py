#!/usr/bin/env python3
"""Weather service for Printomat - sends weather forecasts as print requests."""

import asyncio
import base64
import sys
from datetime import datetime
from io import BytesIO
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import requests

from base import BaseService

# Use non-interactive backend for matplotlib
matplotlib.use('Agg')


class WeatherService(BaseService):
    """Weather service that fetches forecast data and sends it to the printer.

    Fetches weather data from Open-Meteo API, creates temperature and
    precipitation plots, and sends them as print requests.
    """

    def __init__(self, server_url: str, service_name: str, service_token: str,
                 latitude: float, longitude: float, print_hour: int = 8, print_minute: int = 0,
                 print_on_start: bool = False):
        """Initialize the weather service.

        Args:
            server_url: HTTP URL of the server
            service_name: Name to identify this service
            service_token: Authentication token for services
            latitude: Latitude for weather location
            longitude: Longitude for weather location
            print_hour: Hour of day to print (0-23, default: 8 for 8 AM)
            print_minute: Minute of hour to print (0-59, default: 0)
            print_on_start: Whether to print immediately on startup (default: False)
        """
        super().__init__(server_url, service_name, service_token)
        self.latitude = latitude
        self.longitude = longitude
        self.print_hour = print_hour
        self.print_minute = print_minute
        self.print_on_start = print_on_start

    def _fetch_weather_data(self) -> Optional[dict]:
        """Fetch weather data from Open-Meteo API.

        Returns:
            Weather data dict or None if request failed
        """
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": "temperature_2m,precipitation",
            "timezone": "auto"
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Failed to fetch weather data: {e}")
            return None

    def _create_weather_plots(self, data: dict) -> Optional[str]:
        """Create weather plots and return as base64-encoded PNG.

        Args:
            data: Weather data from Open-Meteo API

        Returns:
            Base64-encoded PNG image or None if creation failed
        """
        try:
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            temperatures = hourly.get("temperature_2m", [])
            precipitation = hourly.get("precipitation", [])

            # Parse times and filter for hours 8-24 today
            parsed_times = [datetime.fromisoformat(t) for t in times]
            now = datetime.now()
            today_data = [
                (t, temp, precip)
                for t, temp, precip in zip(parsed_times, temperatures, precipitation)
                if t.date() == now.date() and 8 <= t.hour < 24
            ]

            if not today_data:
                self.logger.warning("No weather data available for today 8am-midnight")
                return None

            plot_times, plot_temps, plot_precip = zip(*today_data)
            hours = [t.hour for t in plot_times]

            # Create figure with two subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)

            # Temperature plot
            ax1.plot(hours, plot_temps, color='gray', linewidth=2)
            ax1.axhline(y=0, color='black', linestyle='-', linewidth=2)
            ax1.set_ylabel('Temperature (°C)', fontsize=12)
            ax1.set_title('Weather Forecast for Today', fontsize=14, fontweight='bold')

            # Ensure y-axis includes at least -5 to +5 around zero
            current_min, current_max = min(plot_temps), max(plot_temps)
            y_min = min(current_min, -5)
            y_max = max(current_max, 5)
            ax1.set_ylim(y_min, y_max)

            ax1.grid(True, alpha=0.3)

            # Precipitation plot
            ax2.bar(hours, plot_precip, color='blue', alpha=0.6)
            ax2.set_xlabel('Hour of Day', fontsize=12)
            ax2.set_ylabel('Precipitation (mm)', fontsize=12)
            ax2.set_ylim(bottom=0)
            ax2.grid(True, alpha=0.3)

            # Set x-axis ticks and limits (tight to data)
            ax2.set_xticks(range(8, 24, 2))
            ax2.set_xlim(8, 23)

            plt.tight_layout()

            # Convert to base64
            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
            plt.close(fig)
            buffer.seek(0)
            image_base64 = base64.b64encode(buffer.read()).decode('utf-8')

            return image_base64

        except Exception as e:
            self.logger.error(f"Failed to create weather plots: {e}", exc_info=True)
            return None

    async def _print_weather(self) -> None:
        """Fetch weather data and send it to the printer."""
        try:
            self.logger.info("Fetching weather data...")
            data = self._fetch_weather_data()

            if data:
                # Create plots
                image_base64 = self._create_weather_plots(data)

                if image_base64:
                    # Send only the image, no text message
                    await self.send_print_request(
                        image=image_base64
                    )
                    self.logger.info("Weather forecast sent to printer")
                else:
                    self.logger.warning("Failed to create plots, skipping this update")
            else:
                self.logger.warning("Failed to fetch weather data, skipping this update")

        except Exception as e:
            self.logger.error(f"Error printing weather: {e}", exc_info=True)

    def _calculate_seconds_until_next_print(self) -> float:
        """Calculate seconds until the next scheduled print time.

        Returns:
            Number of seconds to wait
        """
        now = datetime.now()
        target = now.replace(hour=self.print_hour, minute=self.print_minute, second=0, microsecond=0)

        # If target time has passed today, schedule for tomorrow
        if target <= now:
            target = target.replace(day=target.day + 1)

        return (target - now).total_seconds()

    async def loop(self) -> None:
        """Service loop that fetches and sends weather data once per day at specified time."""
        self.logger.info(
            f"Weather service started (lat={self.latitude}, lon={self.longitude}, "
            f"print time={self.print_hour:02d}:{self.print_minute:02d})"
        )

        # Print on startup if requested
        if self.print_on_start:
            self.logger.info("Printing weather on startup")
            await self._print_weather()

        while True:
            # Calculate time until next print
            seconds_until_print = self._calculate_seconds_until_next_print()
            self.logger.info(f"Next weather print in {seconds_until_print/3600:.1f} hours")

            # Sleep until print time
            await asyncio.sleep(seconds_until_print)

            # Print weather at scheduled time
            self.logger.info("Print time reached")
            await self._print_weather()


    @classmethod
    def from_config(cls, server_url: str, service_name: str, service_token: str, config):
        """Create a WeatherService instance from configuration.

        Args:
            server_url: HTTP URL of the server
            service_name: Name of the service
            service_token: Authentication token
            config: ServiceConfig instance

        Returns:
            WeatherService instance
        """
        # Get weather-specific settings from config
        service_config = config.get_service_config(service_name)

        latitude = service_config.get("latitude", 0.0)
        longitude = service_config.get("longitude", 0.0)
        print_hour = service_config.get("print_hour", 8)
        print_minute = service_config.get("print_minute", 0)
        print_on_start = service_config.get("print_on_start", False)

        # Validate required settings
        if latitude == 0.0 or longitude == 0.0:
            print("Error: latitude and longitude must be set in config.toml")
            sys.exit(1)

        return cls(
            server_url=server_url,
            service_name=service_name,
            service_token=service_token,
            latitude=latitude,
            longitude=longitude,
            print_hour=print_hour,
            print_minute=print_minute,
            print_on_start=print_on_start
        )


def main():
    """Run the weather service."""
    WeatherService.run_from_config()


if __name__ == "__main__":
    main()
