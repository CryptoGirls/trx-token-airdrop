import requests
import json
import sys
import time
import argparse
import datetime
import dateutil.parser as dp
import psycopg2


if sys.version_info[0] < 3:
	print ('python2 not supported, please use python3')
	sys.exit (0)

# Parse command line args
parser = argparse.ArgumentParser(description='TRX payments script')
parser.add_argument('-c', metavar='config.json', dest='cfile', action='store',
                   default='config.json',
                   help='set a config file (default: config.json)')
parser.add_argument('-y', dest='alwaysyes', action='store_const',
                   default=False, const=True,
                   help='automatic yes for log saving (default: no)')
parser.add_argument('--min-payout', type=float, dest='minpayout', action='store',
                   default=None,
                   help='override the minpayout value from config file')

args = parser.parse_args ()
	
# Load the config file
try:
	conf = json.load (open (args.cfile, 'r'))
except:
	print ('Unable to load config file.')
	sys.exit ()
	
if 'logfile' in conf:
	LOGFILE = conf['logfile']
else:
	LOGFILE = 'poollogs.json'

VOTERSLOG = 'voters.json'

ACCOUNTSLOG = 'accounts.json'

fees=conf['fees']


# Override minpayout from command line arg
if args.minpayout != None:
	conf['minpayout'] = args.minpayout


# Fix the node address if it ends with a /
if conf['node'][-1] == '/':
	conf['node'] = conf['node'][:-1]

if conf['nodepay'][-1] == '/':
	conf['nodepay'] = conf['nodepay'][:-1]


def loadLog ():
	try:
		data = json.load (open (LOGFILE, 'r'))
	except:
		print ('Unable to load log file.')
		data = {
			"lastpayout": 1529323200, 
			"accounts": {},
			"skip": []
		}
	return data

def loadVotersLog ():
	try:
		data = json.load (open (VOTERSLOG, 'r'))
	except:
		print ('Unable to load voters file.')
		data = {
			"date": 1529323200, 
			"voters": {}
		}
	return data	

def loadAccountsLog ():
	try:
		data = json.load (open (ACCOUNTSLOG, 'r'))
	except:
		print ('Unable to load accounts file.')
		data = {
			"date": 1529323200, 
			"accounts": {}
		}
	return data		
	
	
def saveLog (log):
	json.dump (log, open (LOGFILE, 'w'), indent=4, separators=(',', ': '))

	
def createPaymentLine (to, amount):
	broadcast=True
	data = {"contract": {"ownerAddress": conf['owneraddress'], "toAddress": to, "assetName": conf['token'], "amount": int( amount )}, "key": conf['pk'], "broadcast": broadcast}
	nodepay = conf['nodepay']
	return 'curl -X POST "' + nodepay + '/api/transaction-builder/contract/transferasset" -H "accept: application/json" -H "Content-Type: application/json" -d \'' + json.dumps (data) + '\' ' + "\n\nsleep 1\n"


def estimatePayouts (log,voterslog,accountslog):

	rew = conf ['amount']
	print ("SHARING: %f %s" % (rew, conf['token']))
	forged=rew
	
	if forged < 0.1:
		return ([], log, 0.0)
	d = voterslog
	a = accountslog

	weight = 0.0
	totalweight = 0.0
	payouts = []
	voters = []

	for x in a['data']:
		if x['address'] in conf['skip']:
			continue
		if conf['private'] and not (x['address'] in conf['whitelist']):
			continue
		for z in d['data']:
			if z['voterAddress']==x['address']:
				weight+=int(conf['percentagebonusforvoters'])/100
		weight+=1
	totalweight=weight

	for x in a['data']:
		if x['address'] in conf['skip']:
			continue
		if conf['private'] and not (x['address'] in conf['whitelist']):
			continue
		for z in d['data']:
			if z['voterAddress']!=x['address']:
				continue
			voters.append({"address": z['voterAddress'], "votes": z['votes']})
	
	print ("HOLDERS no: " + str(len(a['data'])))
	print ("VOTERS no: " + str(len(voters)))
	for x in a['data']:
		if x['address'] in conf['skip']:
			continue
		if conf['private'] and not (x['address'] in conf['whitelist']):
			continue
		weight=1
		payouts.append ({"username": x['address'], "weight": weight, "address": x['address'], "balance": round((weight  * forged) / totalweight, 6), "totalweight": totalweight, "forged": float (rew), "votes": 0 })
		for z in voters:
			if x['address']==z['address']:
				weight=1
				payouts.remove ({"username": x['address'], "weight": weight, "address": x['address'], "balance": round((weight  * forged) / totalweight, 6), "totalweight": totalweight, "forged": float (rew), "votes": 0 })
				weight=1+int(conf['percentagebonusforvoters'])/100
				payouts.append ({"username": x['address'], "weight": weight, "address": x['address'], "balance": round((weight  * forged) / totalweight, 6), "totalweight": totalweight, "forged": float (rew), "votes": z['votes'] })
	return (payouts, log, forged)
	
	
def pool ():
	log = loadLog ()
	voterslog = loadVotersLog ()
	accountslog = loadAccountsLog ()
	(topay, log, forged) = estimatePayouts (log,voterslog,accountslog)
	if len (topay) == 0:
			print ('Nothing to distribute, exiting...')
			return
	f = open ('payments.sh', 'w')
	paymentsno=0
	for x in topay:
		# Create the row if not present
		if not (x['address'] in log['accounts']) and x['balance'] != 0.0:
			log['accounts'][x['address']] = { 'username': x['address'], 'weight': x['weight'] / x['totalweight'] * 100, 'pending': 0.0,'received': 0.0, 'topay': 0.0, 'votes': x['votes'] }

		# Check if the voter has a pending balance
		pending = 0
		if x['address'] in log['accounts']:
			pending = log['accounts'][x['address']]['pending']
			
		# If below minpayout, put in the accounts pending and skip
		if (x['balance'] + pending - fees) < conf['minpayout'] and x['balance'] > 0.0:
			log['accounts'][x['address']]['pending'] += x['balance']
			log['accounts'][x['address']]['weight'] = x['weight'] / x['totalweight'] * 100
			continue
			
		# If above, update the received balance and write the payout line
		log['accounts'][x['address']]['received'] += (x['balance'] + pending)
		log['accounts'][x['address']]['weight'] = x['weight'] / x['totalweight'] * 100
		log['totalweight'] = x['totalweight']
		log['forged'] = x['forged']
		log['todistribute'] = round(x['forged'], 6)
		if pending > 0:
			log['accounts'][x['address']]['pending'] = 0
		
		log['accounts'][x['address']]['topay'] = x['balance'] + pending - fees
		f.write ('echo Sending ' + str (x['balance'] - fees) + ' \(+' + str (pending) + ' pending\) to ' + x['address'] + '\n')
		f.write (createPaymentLine (x['address'], x['balance'] + pending - fees))
		paymentsno+=1

			
	# Handle pending balances
	for y in log['accounts']:
		# If the pending is above the minpayout, create the payout line
		if log['accounts'][y]['pending'] - fees > conf['minpayout']:
			f.write ('echo Sending pending ' + str (log['accounts'][y]['pending']) + ' to ' + y + '\n')
			f.write (createPaymentLine (y, log['accounts'][y]['pending'] - fees))
			paymentsno+=1
			
			log['accounts'][y]['received'] += log['accounts'][y]['pending']
			log['accounts'][y]['pending'] = 0.0
			

	# Donations
	if 'donations' in conf:
		for y in conf['donations']:
			f.write ('echo Sending donation ' + str (conf['donations'][y]) + ' to ' + y + '\n')
			f.write (createPaymentLine (y, conf['donations'][y]))
			paymentsno+=1


	# Donation percentage
	if 'donationspercentage' in conf:
		for y in conf['donationspercentage']:
			am = round((forged * conf['donationspercentage'][y]) / 100, 6)
			
			f.write ('echo Sending donation ' + str (conf['donationspercentage'][y]) + '% \(' + str (am) + 'TRX\) to ' + y + '\n')	
			f.write (createPaymentLine (y, am))
			paymentsno+=1

	f.close ()
	
	# Update last payout
	log['lastpayout'] = int (time.time ())
	log['totalpaid']=0
	log['totalpending']=0
	for z in log['accounts']:
		log['totalpaid']+=round(log['accounts'][z]['received'], 6)
		log['totalpending']+=round(log['accounts'][z]['pending'], 6)

	print ("Number of payments: " + str(paymentsno) + ". Estimated fees cost: " + str(paymentsno*200) + " bandwidth.")
	if args.alwaysyes:
		print ('Saving...')
		saveLog (log)
	else:
		yes = input ('save? y/n: ')
		if yes == 'y':
			saveLog (log)

if __name__ == "__main__":
	pool ()


