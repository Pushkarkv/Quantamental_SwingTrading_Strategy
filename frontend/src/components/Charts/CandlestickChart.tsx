'use client';

import { useEffect, useRef } from 'react';
import { createChart, ColorType, LineStyle, Time, CandlestickSeries } from 'lightweight-charts';
import { useTheme } from '@/context/ThemeContext';

export interface OHLCVData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PredictionData {
  price_on_t0_inr: number;
  predicted_upside_inr: number;
  predicted_downside_inr: number;
  predicted_avg_inr: number;
  board_meeting_date?: string;
}

interface ChartProps {
  data: OHLCVData[];
  prediction?: PredictionData;
}

export default function CandlestickChart({ data, prediction }: ChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (!chartContainerRef.current || data.length === 0) return;

    const isDark = theme === 'dark';
    
    // Theme colors matching globals.css
    const colors = {
      bg: 'transparent',
      textColor: isDark ? '#8b949e' : '#64748b',
      gridColor: isDark ? '#1a2332' : '#f1f5f9',
      upColor: isDark ? '#00d68f' : '#16a34a',
      downColor: isDark ? '#ff6b6b' : '#dc2626',
      lineUp: '#00d68f',
      lineDown: '#ff6b6b',
      lineAvg: '#a78bfa',
      lineT0: '#6c9fff',
    };

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: colors.bg },
        textColor: colors.textColor,
      },
      grid: {
        vertLines: { color: colors.gridColor },
        horzLines: { color: colors.gridColor },
      },
      timeScale: {
        borderColor: colors.gridColor,
        timeVisible: true,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      rightPriceScale: {
        borderColor: colors.gridColor,
      },
      crosshair: {
        mode: 1, // Normal mode
        vertLine: {
          color: isDark ? '#30363d' : '#cbd5e1',
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: isDark ? '#1f2937' : '#e8ecf1',
        },
        horzLine: {
          color: isDark ? '#30363d' : '#cbd5e1',
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: isDark ? '#1f2937' : '#e8ecf1',
        },
      },
    });

    // Candlestick Series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: colors.upColor,
      downColor: colors.downColor,
      borderVisible: false,
      wickUpColor: colors.upColor,
      wickDownColor: colors.downColor,
    });

    const formattedData = data.map((d) => ({
      time: d.time as Time,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));
    
    candleSeries.setData(formattedData);

    // Prediction Lines
    if (prediction) {
      // Create price lines instead of series lines for prediction targets
      // so they extend horizontally across the chart.
      
      // T0 Price
      candleSeries.createPriceLine({
        price: prediction.price_on_t0_inr,
        color: colors.lineT0,
        lineWidth: 2,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: 'T0',
      });

      // Max Upside
      candleSeries.createPriceLine({
        price: prediction.predicted_upside_inr,
        color: colors.lineUp,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'Max Upside',
      });

      // Max Downside
      candleSeries.createPriceLine({
        price: prediction.predicted_downside_inr,
        color: colors.lineDown,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'Max Drawdown',
      });

      // Avg Prediction
      candleSeries.createPriceLine({
        price: prediction.predicted_avg_inr,
        color: colors.lineAvg,
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'Avg Pred',
      });


    }

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [data, prediction, theme]);

  return (
    <div style={{ width: '100%', height: '500px', position: 'relative' }}>
      <div 
        ref={chartContainerRef} 
        style={{ width: '100%', height: '100%' }} 
      />
    </div>
  );
}
