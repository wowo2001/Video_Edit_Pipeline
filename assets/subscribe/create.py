from pathlib import Path
import math, wave, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parent
frames=ROOT/'frames';frames.mkdir(exist_ok=True)
fontpath=ROOT.parent/'fonts/msyh.ttc'
font=ImageFont.truetype(str(fontpath),34)
small=ImageFont.truetype(str(fontpath),20)
S=2;W,H=720,400;fps=30

def ease(x):
 x=max(0,min(1,x));return 1-(1-x)**3

def label(d,box,text,f,fill):
 b=d.textbbox((0,0),text,font=f);d.text(((box[0]+box[2]-(b[2]-b[0]))/2,(box[1]+box[3]-(b[3]-b[1]))/2-b[1]),text,font=f,fill=fill)
for i in range(120):
 t=i/fps
 im=Image.new('RGBA',(W,H));d=ImageDraw.Draw(im)
 y=150+int(28*(1-ease(t/.45)))
 # Soft drop shadow and light card.
 for k in range(12,0,-1):
  d.rounded_rectangle((112-k,y-27-k,608+k,y+105+k),radius=34,fill=(0,0,0,2))
 d.rounded_rectangle((112,y-27,608,y+105),radius=28,fill='#FFFFFF')
 d.text((142,y-10),'小红叔 · 新闻与观点',font=small,fill='#617080')
 click=t>=1.35
 bx=(140,y+27,455,y+84)
 d.rounded_rectangle(bx,radius=16,fill='#E9EEF2' if click else '#E53935')
 label(d,(178,y+27,455,y+84),'已订阅' if click else '订阅小红叔',font,'#304354' if click else 'white')
 if click:
  d.line([(157,y+56),(166,y+65),(182,y+46)],fill='#279575',width=5)
 else:
  d.polygon([(158,y+44),(158,y+68),(176,y+56)],fill='white')
 # Bell, rotating around its top.
 bell=Image.new('RGBA',(100,100));bd=ImageDraw.Draw(bell)
 col='#DAA22A' if t>=2.1 else '#667686'
 bd.ellipse((43,12,57,26),fill=col)
 bd.rounded_rectangle((28,24,72,68),radius=21,fill=col)
 bd.polygon([(28,48),(22,73),(78,73),(72,48)],fill=col)
 bd.ellipse((43,77,57,88),fill=col)
 if t>=2.1:
  bd.arc((10,19,90,86),195,245,fill=col,width=3)
  bd.arc((10,19,90,86),295,345,fill=col,width=3)
 angle=math.sin((t-2.1)*28)*16*max(0,1-(t-2.1)/1.1) if t>=2.1 else 0
 bell=bell.rotate(angle,resample=Image.Resampling.BICUBIC)
 im.alpha_composite(bell,(480,y+5))
 d=ImageDraw.Draw(im)
 # Click rings.
 for at,cx,cy in [(1.35,365,y+65),(2.1,531,y+56)]:
  dt=t-at
  if 0<=dt<.4:
   r=8+dt*70
   d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=(229,57,53,int(190*(1-dt/.4))),width=3)
 # Cursor travels in, clicks, then points to the bell.
 if .55<t<2.65:
  p=ease((t-.55)/.65);cx=650+(365-650)*p;cy=330+(y+65-330)*p
  if t>1.65:
   p=ease((t-1.65)/.4);cx=365+(531-365)*p;cy=y+65-9*p
  d.polygon([(cx,cy),(cx+3,33+cy),(cx+12,25+cy),(cx+23,39+cy),(cx+30,34+cy),(cx+19,20+cy),(cx+32,16+cy)],fill='white',outline='#293745',width=2)
 opacity=ease(t/.25)*(1-ease((t-3.35)/.6))
 im.putalpha(im.getchannel('A').point(lambda a:int(a*opacity)))
 im.save(frames/f'{i:04d}.png')
# Gentle bell with decaying overtones; click is deliberately quiet.
sr=48000;audio=np.zeros(sr*4)
for at,freq,gain in [(1.35,1400,.08),(2.1,1568,.20)]:
 n=int(sr*.85);x=np.arange(n)/sr
 tone=(np.sin(2*np.pi*freq*x)+.32*np.sin(2*np.pi*freq*2.76*x))*np.exp(-x*7)*np.minimum(x/.004,1)*gain
 j=int(at*sr);audio[j:j+n]+=tone
with wave.open(str(ROOT/'sound.wav'),'wb') as f:
 f.setnchannels(1);f.setsampwidth(2);f.setframerate(sr);f.writeframes((audio*32767).astype('<i2').tobytes())
def run(args):subprocess.run(['ffmpeg','-v','error','-y',*args],check=True)
run(['-framerate','30','-i',str(frames/'%04d.png'),'-i',str(ROOT/'sound.wav'),'-c:v','qtrle','-pix_fmt','argb','-c:a','pcm_s16le',str(ROOT/'subscribe_overlay.mov')])
run(['-f','lavfi','-i','color=c=0x14212e:s=720x400:r=30:d=4','-framerate','30','-i',str(frames/'%04d.png'),'-i',str(ROOT/'sound.wav'),'-filter_complex','[0:v][1:v]overlay=shortest=1[v]','-map','[v]','-map','2:a','-c:v','libx264','-pix_fmt','yuv420p','-crf','18','-c:a','aac','-movflags','+faststart','-t','4',str(ROOT/'subscribe_preview.mp4')])
print(ROOT/'subscribe_preview.mp4')
