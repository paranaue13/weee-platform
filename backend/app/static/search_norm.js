/* Κοινή κανονικοποίηση για ΑΝΑΖΗΤΗΣΗ (Windows + Android): πεζά, χωρίς τόνους, και τα ελληνικά γράμματα που μοιάζουν με λατινικά
   θεωρούνται ίδια: Α=A, Β=B, Ε=E, Ζ=Z, Η=H, Ι=I, Κ=K, Μ=M, Ν=N, Ο=O, Ρ=P, Τ=T, Υ=Y, Χ=X. Αριθμοί και λοιποί χαρακτήρες μένουν ως έχουν.
   Εφαρμόζεται ΣΤΗ ΣΥΓΚΡΙΣΗ (και στο κείμενο του χρήστη και στον κωδικό/όνομα)· δεν αλλάζει δεδομένα. Ένα αρχείο, ένας κανόνας. */
(function(){
  var GL={'α':'a','β':'b','ε':'e','ζ':'z','η':'h','ι':'i','κ':'k','μ':'m','ν':'n','ο':'o','ρ':'p','τ':'t','υ':'y','χ':'x'};
  window.searchNorm=function(x){
    return String(x==null?'':x).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'').replace(/ς/g,'σ').replace(/[αβεζηικμνορτυχ]/g,function(c){return GL[c]});
  };
  // "κείμενο".sn() ≡ searchNorm("κείμενο") — για να αντικαθιστά απλά το .toLowerCase()/.toLocaleLowerCase('el') στα σημεία αναζήτησης
  Object.defineProperty(String.prototype,'sn',{value:function(){return window.searchNorm(String(this))},configurable:true,writable:true});
})();
