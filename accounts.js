const xhr = require('axios')
const fs = require('fs');

// file
const outFile = 'accounts.json';

async function loadAccounts() {
  let start = 0;
  let results = [];

  while (true) {
    console.log("start: " + start);
    let {data} = await xhr.get("https://api.tronscan.org/api/token/TOKEN_NAME/address", {
      params: {
        limit: 100,
        sort: '-balance',
        start,
      }
    });

    //console.log("accounts: " + data.data.length)

    if (data.data.length === 0) {
      break;
    }

    start += 100;

    results = [...results, ...data.data];
  }

  return  results ;
}

loadAccounts().then(accounts => {

  fs.writeFile(outFile, '{"data":' + JSON.stringify(accounts) + "}", 'utf8', () => {
    console.log('done');
  });
})
