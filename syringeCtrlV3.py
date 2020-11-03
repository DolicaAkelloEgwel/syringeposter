from tkinter import *
from tkinter.ttk import *
import time
import serial
import io

#
# Runs with python 3
# works for microlab 500
#
root = Tk()
master = Frame(root, name='master')
master.pack(fill=BOTH)  # fill both sides of the parent
root.title('Syringe Control')  # title for top-level window
root.protocol("WM_DELETE_WINDOW", master.quit)  #quit if the window is deleted

# This is to add a second window
'''
syrStat = Toplevel()
syrStat.title("Syringe Status")
msg = Message(syrStat, text='test    fre          fre')
msg.pack()
button = Button(syrStat, text="Dismiss", command=syrStat.destroy)
button.pack()
'''

syrCtrl = Notebook(master, name='syrCtrl')  # create Notebook in "master"
syrCtrl.pack(fill=BOTH, padx=2, pady=3)  # fill "master" but pad sides -> frame appears
syrCtrlMan = Frame(syrCtrl, name='syrCtrlMan') # create foo tab in Notebook
syrCtrlMan.pack(fill=BOTH)

# Create Init
syrCtrlManInit = LabelFrame(syrCtrlMan, text='Init', name='syrCtrlManLeftInit', relief=GROOVE, borderwidth=2, labelanchor=N)
syrCtrlManInit.grid(row = 0, column = 0, columnspan = 2)
InitBut = Button(syrCtrlManInit, text="Init", command=lambda: syrCtrl().sendCmd('aXS30R'))
InitBut.grid(row = 0, column = 0, rowspan = 2, padx=2, pady=3)
Label(syrCtrlManInit, text="Fine Speed").grid(row = 0, column = 1)
ManFineSpeed = Entry(syrCtrlManInit, width=11)
ManFineSpeed.insert(END, 250)
ManFineSpeed.grid(row = 0, column = 2)
Label(syrCtrlManInit, text="Coarse Speed").grid(row = 1, column = 1)
ManCoarseSpeed = Entry(syrCtrlManInit, width=11)
ManCoarseSpeed.insert(END, 50)
ManCoarseSpeed.grid(row = 1, column = 2)

# Create 'Left Syringe' frame
syrCtrlManLeft = LabelFrame(syrCtrlMan, text='Left Syringe', name='syrCtrlManLeft', relief=GROOVE, borderwidth=2)
syrCtrlManLeft.grid(row = 1, column = 0, padx=2, pady=3)

# Create 'Pick Up' frame in 'Left Syringe' frame
syrCtrlManLeftPickUp = LabelFrame(syrCtrlManLeft, text='Pick-Up (Fine Speed)', name='syrCtrlManLeftPickUp', relief=GROOVE, borderwidth=2, labelanchor=N)
syrCtrlManLeftPickUp.grid(row = 0, column = 0)
PickUp1 = Button(syrCtrlManLeftPickUp, text="PickUp\n1 step", command=lambda: syrCtrl().singleSyrMove('B', 'I', 'P', 1, ManFineSpeed.get()))
PickUp1.grid(row = 0, column = 0, rowspan = 2)
PickUp2 = Button(syrCtrlManLeftPickUp, text="PickUp\n5 steps", command=lambda: syrCtrl().singleSyrMove('B', 'I', 'P', 5, ManFineSpeed.get()))
PickUp2.grid(row = 0, column = 1, rowspan = 2)
PickUp3 = Button(syrCtrlManLeftPickUp, text="PickUp\nSpecified", command=lambda: syrCtrl().singleSyrMove('B', 'I', 'P', int(ManPickUpStep.get()), ManFineSpeed.get()))
PickUp3.grid(row = 0, column = 2, rowspan = 2)
Label(syrCtrlManLeftPickUp, text="<-Steps", ).grid(row = 0, column = 4)
ManPickUpStep = Entry(syrCtrlManLeftPickUp, width=11)
ManPickUpStep.insert(END, 50)
ManPickUpStep.grid(row = 1, column = 4)

# Create 'other' frame in 'Left Syringe' frame
syrCtrlManLeftOther = LabelFrame(syrCtrlManLeft, text='Other (Coarse Speed)', name='syrCtrlManLeftOther', relief=GROOVE, borderwidth=2, labelanchor=N)
syrCtrlManLeftOther.grid(row = 1, column = 0)
LeftOther1 = Button(syrCtrlManLeftOther, text="Empty\nto\nwaste", command=lambda: syrCtrl().singleSyrMove('B', 'O', 'M', 0, ManCoarseSpeed.get()))
LeftOther1.grid(row = 0, column = 0)
LeftOther2 = Button(syrCtrlManLeftOther, text="Empty\nto\nmylar", command=lambda: syrCtrl().singleSyrMove('B', 'I', 'M', 0, ManCoarseSpeed.get()))
LeftOther2.grid(row = 0, column = 1)
LeftOther3 = Button(syrCtrlManLeftOther, text="Fill\nfrom\nwaste", command=lambda: syrCtrl().singleSyrMove('B', 'O', 'M', 2000, ManCoarseSpeed.get()))
LeftOther3.grid(row = 0, column = 2)
LeftOther4 = Button(syrCtrlManLeftOther, text="Fill\nfrom\nmylar", command=lambda: syrCtrl().singleSyrMove('B', 'I', 'M', 2000, ManCoarseSpeed.get()))
LeftOther4.grid(row = 0, column = 4)

# Create 'Right Syringe' frame
syrCtrlManRight = LabelFrame(syrCtrlMan, text='Right Syringe', name='syrCtrlManRight', relief=GROOVE, borderwidth=2)
syrCtrlManRight.grid(row = 1, column = 1, padx=2, pady=3)
# Create 'Dispence' frame in 'Right Syringe' frame
syrCtrlManRightDispence = LabelFrame(syrCtrlManRight, text='Dispence (Fine Speed)', name='syrCtrlManRightDispence', relief=GROOVE, borderwidth=2, labelanchor=N)
syrCtrlManRightDispence.grid(row = 0, column = 0)
Dispence1 = Button(syrCtrlManRightDispence, text="Dispence\n1 step", command=lambda: syrCtrl().singleSyrMove('C', 'O', 'D', 1, ManFineSpeed.get()))
Dispence1.grid(row = 0, column = 0, rowspan = 2)
Dispence2 = Button(syrCtrlManRightDispence, text="Dispence\n5 steps", command=lambda: syrCtrl().singleSyrMove('C', 'O', 'D', 5, ManFineSpeed.get()))
Dispence2.grid(row = 0, column = 1, rowspan = 2)
Dispence3 = Button(syrCtrlManRightDispence, text="Dispence\nSpecified", command=lambda: syrCtrl().singleSyrMove('C', 'O', 'D', int(ManDispStep.get()), ManFineSpeed.get()))
Dispence3.grid(row = 0, column = 2, rowspan = 2)
Label(syrCtrlManRightDispence, text="<-Steps", ).grid(row = 0, column = 4)
ManDispStep = Entry(syrCtrlManRightDispence, width=11)
ManDispStep.insert(END, 50)
ManDispStep.grid(row = 1, column = 4)

# Create 'other' frame in 'Right Syringe' frame
syrCtrlManRightOther = LabelFrame(syrCtrlManRight, text='Other (Coarse Speed)', name='syrCtrlManRightOther', relief=GROOVE, borderwidth=2, labelanchor=N)
syrCtrlManRightOther.grid(row = 1, column = 0)
RightOther1 = Button(syrCtrlManRightOther, text="Empty\nto\nsupply", command=lambda: syrCtrl().singleSyrMove('C', 'I', 'M', 0, ManCoarseSpeed.get()))
RightOther1.grid(row = 0, column = 0)
RightOther2 = Button(syrCtrlManRightOther, text="Empty\nto\nmylar", command=lambda: syrCtrl().singleSyrMove('C', 'O', 'M', 0, ManCoarseSpeed.get()))
RightOther2.grid(row = 0, column = 1)
RightOther3 = Button(syrCtrlManRightOther, text="Fill\nfrom\nsupply", command=lambda: syrCtrl().singleSyrMove('C', 'I', 'M', 2000, ManCoarseSpeed.get()))
RightOther3.grid(row = 0, column = 2)
RightOther4 = Button(syrCtrlManRightOther, text="Fill\nfrom\nmylar", command=lambda: syrCtrl().singleSyrMove('C', 'O', 'M', 2000, ManCoarseSpeed.get()))
RightOther4.grid(row = 0, column = 4)

# Create Stop
syrCtrlManStop = LabelFrame(syrCtrlMan, text='Stop', name='syrCtrlManLeftStop', relief=GROOVE, borderwidth=2, labelanchor=N)
syrCtrlManStop.grid(row = 2, column = 0, columnspan = 2, padx=2, pady=3)
Stop = Button(syrCtrlManStop, text="STOP", command=lambda: syrCtrl().sendCmd('aK'))
Stop.grid(row = 0, column = 0, rowspan = 2)

# add 'Manual tab' tab to Notebook
syrCtrl.add(syrCtrlMan, text="Manual Mode")  

# repeat for each tab
# line 1
syrCtrlAuto = Frame(master, name='syrCtrlAuto')
Label(syrCtrlAuto, text="Bottle Speed").grid(row = 0, column = 0)
bottleSpeed = Entry(syrCtrlAuto, width=11)
bottleSpeed.insert(END, 50)
bottleSpeed.grid(row = 0, column = 1)
Label(syrCtrlAuto, text="Syr Size (mL)").grid(row = 0, column = 2)
syrSize = Entry(syrCtrlAuto, width=11)
syrSize.insert(END, 25)
syrSize.grid(row = 0, column = 3)
btn6 = Button(syrCtrlAuto, 
				text="Check Time",
				command=lambda : syrCtrl().checkTime(int(cycleNumberFlow.get())))
btn6.grid(row = 0, column = 4)

Label(syrCtrlAuto, text="Flow Speed").grid(row = 1, column = 0)
flowSpeed = Entry(syrCtrlAuto, width=11)
flowSpeed.insert(END, 250)
flowSpeed.grid(row = 1, column = 1)
Label(syrCtrlAuto, text="N cycle").grid(row = 1, column = 2)
cycleNumberFlow = Entry(syrCtrlAuto, width=11)
cycleNumberFlow.insert(END, 5)
cycleNumberFlow.grid(row = 1, column = 3)
btn6 = Button(syrCtrlAuto, 
				text="Flow !",
				command=lambda : syrCtrl().flowCycle(int(cycleNumberFlow.get())))
btn6.grid(row = 1, column = 4)

btn5 = Button(syrCtrlAuto, 
				text="getReady", 
				command=lambda : syrCtrl().dualSyrMove('O', 'M', 0, 20, 'I', 'M', 2000, 20))
btn5.grid(row = 2, column = 0)

btn7 = Button(syrCtrlAuto, 
				text="Flush", 
				command=lambda : syrCtrl().flush(int(cycleNumberFlow.get())))
btn7.grid(row = 3, column = 0)
	






syrCtrl.add(syrCtrlAuto, text="Auto Mode") #end of the Auto tab

class syrCtrl():

	def setup(self):
		syrCtrl().sendSimpleCmd('1a')
		syrCtrl().sendCmd('aBYSM1R') # set full resolution -> 2000 step per strokes
		syrCtrl().sendCmd('aCYSM1R') # set full resolution -> 2000 step per strokes
		syrCtrl().sendCmd('aCYSN0R') # eliminates backlash
		syrCtrl().sendCmd('aBYSN0R') # eliminates backlash

	def sendSimpleCmd(self, cmd2send):
		# does not check the 'ack'
		sio.write(cmd2send + '\r') #??? removed unicode here
		sio.flush()
		result = sio.readline() #??? dropped '.decode('utf8')'
		response = result[1:-1]
		print('response is :', response[0:1])
		return response
		
	def sendCmd(self, cmd2send):
		sio.write(cmd2send + '\r') #??? removed unicode here
		sio.flush()
		result = sio.readline() #??? dropped '.decode('utf8')'
		ack = result[:1]
		#print('sould be 6 :',ord(ack[0]))
		if ord(ack[0]) != (6 or 49):
			raise Exception("bad response {}".format(ord(ack)))
	# strip off leading ack and trailin CR
		response = result[1:-1]
		#print('response is :', response[0:1])
		return response

	def moveAndWait(self, cmdMove):
		#global pl
		try:	
			print('execute move', cmdMove)
			syrCtrl().sendCmd(cmdMove)
			while True:
				time.sleep(.2)
				response = syrCtrl().sendCmd('aF')
				# posLeft = getSyrPos()[0]
				# pl.config(text=getSyrPos()[0])
				if response[0:1] == 'Y':
					break
		except Exception as e:
			print('it broke')

	def singleSyrMove(self, syr, valve, type, step, speed):
		cmd = 'a'+syr+valve+type+str(step)+'S'+str(speed)+'R'
		syrCtrl().moveAndWait(cmd)

	def dualSyrMove(self, valveL, typeL, stepL, speedL, valveR, typeR, stepR, speedR):
		cmd = ('a'+
			'B'+valveL+typeL+str(stepL)+'S'+str(speedL)+
			'C'+valveR+typeR+str(stepR)+'S'+str(speedR)+'R')
		syrCtrl().moveAndWait(cmd)
	
	def syrFlush(self, cycleNum):
		for i in range(cycleNum):
			syrCtrl().dualSyrMove('O', 'M', 2000, 20, 'I', 'M', 2000, 20)
			syrCtrl().dualSyrMove('I', 'M', 0, ManCoarseSpeed.get(), 'O', 'M', 0, ManCoarseSpeed.get())
			
	def flowCycle(self, cycleNumber):
		for i in range(cycleNumber):
			time.sleep(.5)
			syrCtrl().getReady()
			time.sleep(.5)
			syrCtrl().dualSyrMove('I', 'M', 2000, flowSpeed.get(), 'O', 'M', 0, flowSpeed.get())
		
	def getReady(self):
		syrCtrl().dualSyrMove('O', 'M', 0, bottleSpeed.get(), 'I', 'M', 2000, bottleSpeed.get())
		
	def checkTime(self, cycleNumber):
		time = cycleNumber * (int(bottleSpeed.get()) + int(flowSpeed.get()))
		volume = cycleNumber * int(syrSize.get())
		print(('Will flow {} mL in {:.1f} minutes or {:.2f} hours').format(volume, time / 60, time / 3600))
		
	def flush(self, cycleNumber):
		for i in range(cycleNumber):
			time.sleep(.5)
			syrCtrl().dualSyrMove('I', 'M', 2000, bottleSpeed.get(), 'I', 'M', 2000, bottleSpeed.get())
			time.sleep(.5)
			syrCtrl().dualSyrMove('O', 'M', 0, flowSpeed.get(), 'O', 'M', 0, flowSpeed.get())





if __name__ == "__main__":
	# serial config
	ser = serial.Serial(
	port='\\.\COM3',
	baudrate=9600,
	parity=serial.PARITY_ODD,
	stopbits=serial.STOPBITS_ONE,
	bytesize=serial.SEVENBITS,
	timeout=.02
	)
	sio = io.TextIOWrapper(io.BufferedRWPair(ser, ser))
	#time.sleep(10)
	syrCtrl().setup()
	
	master.mainloop()

'''
class syrCtrl():

    def sendCmd(self, cmd2send):
        print cmd2send

    def moveAndWait(self, cmdMove):
        print cmdMove

    def singleSyrMove(self, par):
        print 'single move', par

    def dualSyrMove(self, par):
        print 'dual move', par


#syrCtrl().singleSyrMove('maybe')
'''

"""

class test():
    def printTata(self):
        # type: () -> object
        print 'tata'

    def printToto(self):
        print 'toto'



test2 = test()

test2.printTata()
"""
'''

import Tkinter as tk

class Notepad(tk.Frame):
    def __init__(self, parent):
        tk.Frame.__init__(self, parent)
        self.text = tk.Text(self, wrap="word")
        self.vsb = tk.Scrollbar(self, orient="vertical", comman=self.text.yview)
        self.text.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

def main():
    root = tk.Tk()
    Notepad(root).pack(fill="both", expand=True)
    for i in range(5):
        top = tk.Toplevel(root)
        Notepad(top).pack(fill="both", expand=True)

    root.mainloop()

if __name__ == "__main__":
    main()

'''

'''
class Demo1:
    def __init__(self, master):
        self.master = master
        self.frame = Frame(self.master)
        self.button1 = Button(self.frame, text = 'New Window', width = 25, command = self.new_window)
        self.button1.pack()
        self.frame.pack()

    def new_window(self):
        self.newWindow = Toplevel(self.master)
        self.app = Demo2(self.newWindow)

class Demo2:
    def __init__(self, master):
        self.master = master
        self.frame = Frame(self.master)
        self.quitButton = Button(self.frame, text = 'Quit', width = 25, command = self.close_windows)
        self.quitButton.pack()
        self.frame.pack()

    def close_windows(self):
        self.master.destroy()

def main():
    root = Tk()
    app = Demo1(root)
    root.mainloop()

if __name__ == '__main__':
    main()



'''
