 /* Geogebra to Asymptote conversion, documentation at artofproblemsolving.com/Wiki go to User:Azjps/geogebra */
import graph; size(23.657568010802137cm); 
real labelscalefactor = 0.5; /* changes label-to-point distance */
pen dps = linewidth(0.7) + fontsize(10); defaultpen(dps); /* default pen style */ 
pen dotstyle = black; /* point style */ 
real xmin = -12.068963770692251, xmax = 11.588604240109886, ymin = -13.226685833547432, ymax = 10.430882177254706;  /* image dimensions */
pen qqwuqq = rgb(0.,0.39215686274509803,0.); pen qqwwtt = rgb(0.,0.4,0.2); 

draw(circle((3.790432682092047,3.7904326820920473), 5.360481306276799), linewidth(2.8) + qqwwtt); 
draw(arc((0.,0.),0.4474949812888172,0.,5.88925843141408)--(0.,0.)--cycle, linewidth(2.) + qqwuqq); 
draw(arc((0.,0.),0.4474949812888172,0.,5.889258431414142)--(0.,0.)--cycle, linewidth(2.) + red); 
 /* draw figures */
draw((0.3245803449593016,-0.72497316706703)--(3.009550232692205,-0.72497316706703), linewidth(4.) + qqwuqq); 
draw((0.45882883934594676,-1.4260486377528436)--(3.14379872707885,-1.4260486377528436), linewidth(4.) + qqwuqq); 
draw((0.414079341217065,-4.692762001161209)--(3.0990492289499683,-4.692762001161209), linewidth(4.) + qqwuqq); 
draw((0.44391233996965285,-2.2912056015778903)--(3.1288822277025563,-2.2912056015778903), linewidth(4.) + qqwuqq); 
draw((0.3842463424644772,-3.3950265554236396)--(3.0692162301973807,-3.3950265554236396), linewidth(4.) + qqwuqq); 
draw((0.3991628418407711,-4.096102026109453)--(3.0841327295736747,-4.096102026109453), linewidth(4.) + qqwuqq); 
draw((0.,-5.3604813062767995)--(0.,0.), linewidth(2.)); 
 /* dots and labels */
dot((0.5930780795596324,-0.72497316706703),dotstyle);
label("$Arz = 36^{\\circ}$", (0.42899584059335893,-0.5012256764226214), NE * labelscalefactor);
dot((0.,0.),dotstyle); 
dot((-5.3604813062767995,0.),linewidth(4.pt) + dotstyle); 
dot((5.3604813062767995,0.),linewidth(4.pt) + dotstyle); 
dot((0.,-5.3604813062767995),linewidth(3.pt) + dotstyle); 
dot((0.,5.3604813062767995),linewidth(3.pt) + dotstyle); 
dot((2.9991086831287994,-1.4260486377528436),dotstyle);
label("$Oola = 340.6^{\\circ}$", (2.830552240176678,-1.202301147108435), NE * labelscalefactor);
dot((-1.3211371083103396,-5.195128157802113),linewidth(6.pt) + dotstyle); 
dot((0.9361568193873518,-4.692762001161209),dotstyle);
label("$BoadSeva = 17.5^{\\circ}$", (0.7720753262481188,-4.469014510516801), NE * labelscalefactor);
dot((1.5626497931916958,-2.2912056015778903),dotstyle);
label("$Taghvim = 150^{\\circ}$", (1.398568300052463,-2.0674581109334818), NE * labelscalefactor);
dot((0.3842463424644774,-3.3950265554236396),dotstyle);
label("$ArzGhamar = -5.3^{\\circ}$", (0.22016484932524427,-3.171279064779231), NE * labelscalefactor);
dot((0.3991628418407711,-4.096102026109453),dotstyle);
label("$TaghvimGhamar = 0^{\\circ}$", (0.23508134870153818,-3.8723545354650444), NE * labelscalefactor);
dot((-0.008219040056843596,-5.360475005288578),linewidth(4.pt) + dotstyle); 
dot((-0.008219040056843839,5.360475005288576),linewidth(4.pt) + dotstyle); 
clip((xmin,ymin)--(xmin,ymax)--(xmax,ymax)--(xmax,ymin)--cycle); 
 /* end of picture */